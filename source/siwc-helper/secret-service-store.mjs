import { createCipheriv, createDecipheriv, randomBytes, timingSafeEqual } from "node:crypto";
import { spawn } from "node:child_process";

// Secret Service is the Linux OS credential store, commonly backed by GNOME
// Keyring or KWallet. Keep keys out of argv, environment variables and files.
// Never substitute plaintext storage if Secret Service is unavailable.
export function createSecretToolRunner({ spawnImpl = spawn, binary = "secret-tool", timeoutMs = 60000 } = {}) {
  return function runSecretTool(args, input = "") {
    return new Promise((resolve, reject) => {
      let child;
      try {
        child = spawnImpl(binary, args, { stdio: ["pipe", "pipe", "pipe"] });
      } catch (error) {
        reject(error);
        return;
      }
      let stdout = "";
      let stderr = "";
      let settled = false;
      const finish = (error, result) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        if (error) reject(error);
        else resolve(result);
      };
      const timer = setTimeout(() => {
        child.kill();
        finish(new Error("Linux Secret Service operation timed out"));
      }, timeoutMs);
      child.on("error", error => finish(error));
      child.stdout.on("data", chunk => {
        stdout += chunk.toString("utf8");
        if (stdout.length > 8192) {
          child.kill();
          finish(new Error("Linux Secret Service returned an oversized response"));
        }
      });
      child.stderr.on("data", chunk => {
        stderr += chunk.toString("utf8");
        if (stderr.length > 8192) {
          child.kill();
          finish(new Error("Linux Secret Service returned an oversized error"));
        }
      });
      child.on("close", (code, signal) => {
        if (code === 0) finish(null, { stdout, stderr });
        else {
          const error = new Error("Linux Secret Service command failed" + (signal ? " (signal)" : ""));
          error.exitCode = code;
          error.stderr = stderr;
          finish(error);
        }
      });
      child.stdin.on("error", () => {}); // EPIPE is reported by child close/error.
      child.stdin.end(input);
    });
  };
}

function decodeKey(output) {
  const encoded = output.trim();
  if (!/^[A-Za-z0-9+/]{43}=$/.test(encoded)) {
    throw new Error("Linux Secret Service encryption key has invalid encoding");
  }
  const key = Buffer.from(encoded, "base64");
  if (key.length !== 32 || key.toString("base64") !== encoded) {
    throw new Error("Linux Secret Service encryption key has invalid length");
  }
  return key;
}

// An immutable random key ID lives in the AES-GCM envelope; each new key is
// written under a unique Secret Service attribute. secret-tool "store" would
// otherwise UPDATE any matching item, which could irrecoverably destroy
// encrypted profiles. Reuse the key in memory after a successful decrypt.
// The connection store's interprocess file lock serializes profile writes.
export function createSecretServiceEncryption({
  run = createSecretToolRunner(),
  account,
  service = "com.claudex.siwc.encryption-key",
  randomBytesImpl = randomBytes
}) {
  if (!account) throw new Error("Secret Service account must be specified");
  let cached = null;
  const attrs = id => ["application", "claudex", "service", service, "account", account, "key-id", id];
  async function lookup(id) {
    let value;
    try {
      value = await run(["lookup", ...attrs(id)]);
    } catch (error) {
      // A key that genuinely does not exist is NOT a reason to create one
      // during decryption. Locked, inaccessible and missing all fail closed.
      throw new Error("Claudex cannot read its Linux Secret Service encryption key; existing credentials were preserved", { cause: error });
    }
    return decodeKey(value.stdout);
  }
  return {
    id: "claudex-secret-service-aes256gcm-v1",
    async isAvailable() { return process.platform === "linux"; },
    async encrypt(plaintext) {
      if (!cached) {
        const id = randomBytesImpl(16).toString("hex");
        const key = randomBytesImpl(32);
        if (key.length !== 32 || !/^[0-9a-f]{32}$/.test(id)) throw new Error("Linux encryption randomness unavailable");
        // Unique, unpredictable key IDs mean that even concurrent creation
        // cannot overwrite an earlier key (except with negligible collision).
        try {
          await run(["store", "--label=Claudex SIWC encryption key", ...attrs(id)], key.toString("base64"));
          const stored = await lookup(id);
          if (!timingSafeEqual(stored, key)) throw new Error("New Secret Service key changed during creation");
        } catch (error) {
          throw new Error("Claudex could not create a Linux Secret Service key; refusing unencrypted credentials", { cause: error });
        }
        cached = { id, key };
      }
      const iv = randomBytesImpl(12);
      const cipher = createCipheriv("aes-256-gcm", cached.key, iv);
      const ciphertext = Buffer.concat([cipher.update(plaintext, "utf8"), cipher.final()]);
      return Buffer.concat([
        Buffer.from([2]), Buffer.from(cached.id, "hex"), iv, cipher.getAuthTag(), ciphertext
      ]);
    },
    async decrypt(bytes) {
      const buf = Buffer.from(bytes);
      if (buf.length < 45 || buf[0] !== 2) {
        throw new Error("Unsupported Claudex Linux credential encryption format");
      }
      const id = buf.subarray(1, 17).toString("hex");
      const key = cached?.id === id ? cached.key : await lookup(id);
      const decipher = createDecipheriv("aes-256-gcm", key, buf.subarray(17, 29));
      decipher.setAuthTag(buf.subarray(29, 45));
      const result = Buffer.concat([decipher.update(buf.subarray(45)), decipher.final()]).toString("utf8");
      cached = { id, key }; // Reuse the existing OS key for subsequent writes.
      return result;
    }
  };
}
