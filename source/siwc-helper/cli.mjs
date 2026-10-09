#!/usr/bin/env node
import { createChatGPT } from "./node_modules/@siwc/local/dist/index.js";
import { ConnectionStore } from "./node_modules/@siwc/local/dist/storage.js";
import { createCipheriv, createDecipheriv, randomBytes, randomUUID, timingSafeEqual } from "node:crypto";
import { createKeychainKeyReader } from "./keychain-store.mjs";
import { createSecretServiceEncryption } from "./secret-service-store.mjs";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { homedir, userInfo } from "node:os";
import { join, resolve } from "node:path";
import { mkdir, chmod, readFile } from "node:fs/promises";

const execFileAsync = promisify(execFile);
const appId = "claudex";
const appName = "Claudex";
const storageDir = resolve(process.env.CLAUDEX_SIWC_DIR || join(homedir(), ".config", "claudex", "chatgpt"));
const service = "com.claudex.siwc.encryption-key";
const account = userInfo().username;
const keychain = "/usr/bin/security";

// Decryption must never create or replace an encryption key.
const keychainKey = createKeychainKeyReader({ execFileAsync, keychain, account, service });

const credentialEncryption = process.platform === "linux"
  ? createSecretServiceEncryption({ account, service }) : {
  id: "claudex-keychain-aes256gcm-v1",
  async isAvailable() { return process.platform === "darwin"; },
  async encrypt(plaintext) {
    const key = await keychainKey({ createIfMissing: true });
    const iv = randomBytes(12);
    const cipher = createCipheriv("aes-256-gcm", key, iv);
    const ciphertext = Buffer.concat([cipher.update(plaintext, "utf8"), cipher.final()]);
    return Buffer.concat([Buffer.from([1]), iv, cipher.getAuthTag(), ciphertext]);
  },
  async decrypt(bytes) {
    const buf = Buffer.from(bytes);
    if (buf.length < 30 || buf[0] !== 1) throw new Error("unsupported Claudex credential format");
    const key = await keychainKey();
    const decipher = createDecipheriv("aes-256-gcm", key, buf.subarray(1,13));
    decipher.setAuthTag(buf.subarray(13,29));
    return Buffer.concat([decipher.update(buf.subarray(29)), decipher.final()]).toString("utf8");
  }
};

await mkdir(storageDir, { recursive: true, mode: 0o700 });
await chmod(storageDir, 0o700).catch(() => {});
const authUrlFile = process.env.CLAUDEX_SIWC_AUTH_URL_FILE;
const openBrowser = authUrlFile ? async (url) => {
  const { writeFile, chmod } = await import("node:fs/promises");
  await writeFile(authUrlFile, url + "\n", { mode: 0o600 });
  await chmod(authUrlFile, 0o600).catch(() => {});
} : undefined;
const config = { appName, appId, redirectPort: 0, storageDir, credentialEncryption, sendHostId: true, ...(openBrowser ? { openBrowser } : {}) };
const client = createChatGPT(config);
const store = new ConnectionStore(storageDir, credentialEncryption);

function safePrint(value) { process.stdout.write(JSON.stringify(value) + "\n"); }

async function readActive() {
  return store.withLock(async () => {
    const saved = await store.read();
    if (!saved?.activeProfileId) return undefined;
    return saved.profiles.find((p) => p.id === saved.activeProfileId);
  });
}

async function tokenRecord() {
  let profile = await readActive();
  if (!profile?.credentials || profile.status !== "connected") throw new Error("No connected ChatGPT profile. Run: claudex login");
  if (!profile.scopes?.includes("chatgpt.tokens.use.direct")) throw new Error("ChatGPT plan usage is not enabled for this profile.");
  if (profile.credentials.expiresAt <= Date.now() + 60_000 || profile.pendingRefresh) {
    await client.listModels();
    profile = await readActive();
  }
  if (!profile?.credentials || profile.credentials.expiresAt <= Date.now()) throw new Error("ChatGPT access token is unavailable after refresh.");
  return { access_token: profile.credentials.accessToken, expires_at: profile.credentials.expiresAt, profile_id: profile.id };
}

const cmd = process.argv[2] || "status";
try {
  if (cmd === "login") {
    const saved = await store.withLock(async () => await store.read());
    const pending = !saved?.activeProfileId && saved?.pendingRegistrations?.length === 1 ? saved.pendingRegistrations[0] : undefined;
    const session = await client.signIn({ ...(pending ? { profileId: pending.id } : {}), reconsent: process.argv.includes("--reconsent") });
    if (!session.sharing) throw new Error("Signed in, but ChatGPT plan usage permission was not granted.");
    const models = await client.listModels();
    safePrint({ status: session.status, sharing: session.sharing, profileId: session.profileId, identity: session.identity, models: models.map(m => ({slug:m.slug, displayName:m.displayName})) });
  } else if (cmd === "salvage-registration") {
    const originalPath = process.argv[3];
    if (!originalPath) throw new Error("salvage-registration requires the original authorization URL file");
    const chunks = []; for await (const chunk of process.stdin) chunks.push(chunk);
    const callback = new URL(Buffer.concat(chunks).toString("utf8").trim());
    const authorization = new URL((await readFile(originalPath, "utf8")).trim());
    if (callback.hostname !== "127.0.0.1" || callback.pathname !== "/auth/callback") throw new Error("Callback URL is not the expected loopback callback");
    const got = Buffer.from(callback.searchParams.get("state") || "");
    const expected = Buffer.from(authorization.searchParams.get("state") || "");
    if (!got.length || got.length !== expected.length || !timingSafeEqual(got, expected)) throw new Error("Callback state does not match the original authorization transaction");
    const clientId = callback.searchParams.get("client_id");
    if (!clientId || !/^[a-zA-Z0-9_-]{1,200}$/.test(clientId) || clientId === "dynamic_agent_client") throw new Error("Callback did not contain a valid issued client ID");
    await store.withLock(async () => {
      const saved = (await store.read()) ?? { version: 2, profiles: [], pendingRegistrations: [] };
      saved.pendingRegistrations ??= []; saved.profiles ??= [];
      if (!saved.pendingRegistrations.some((x) => x.clientId === clientId) && !saved.profiles.some((x) => x.clientId === clientId)) {
        saved.pendingRegistrations.push({ id: randomUUID(), label: "Connection 1", clientId, savedAt: new Date().toISOString() });
        await store.write(saved);
      }
    });
    safePrint({ registration: "saved", code_reused: false });
  } else if (cmd === "status") {
    const session = await client.getSession();
    safePrint(session);
  } else if (cmd === "models") {
    const models = await client.listModels();
    safePrint(models);
  } else if (cmd === "token") {
    safePrint(await tokenRecord());
  } else if (cmd === "logout") {
    await client.signOut();
    safePrint({ status: "disconnected" });
  } else if (cmd === "disconnect") {
    await client.disconnect();
    safePrint({ status: "disconnected", revoked: true });
  } else {
    throw new Error("Usage: claudex-siwc <login|status|models|token|logout|disconnect>");
  }
} catch (error) {
  const out = { error: error?.code || "siwc_error", message: error?.message || String(error), retryable: Boolean(error?.retryable) };
  process.stderr.write(JSON.stringify(out) + "\n");
  process.exit(1);
}
