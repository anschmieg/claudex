import test from "node:test";
import assert from "node:assert/strict";
import { randomBytes } from "node:crypto";
import { createSecretServiceEncryption } from "./secret-service-store.mjs";

// This simulates the Secret Service IPC contract, never a real profile/keyring.
function fakeService() {
  const secrets = new Map();
  const calls = [];
  let failure = null;
  const run = async (argv, stdin = "") => {
    calls.push({ argv: [...argv], inputPresent: Boolean(stdin) });
    if (failure) throw failure;
    const id = argv[argv.indexOf("key-id") + 1];
    if (argv[0] === "store") {
      if (secrets.has(id)) throw new Error("Test caught a destructive overwrite");
      secrets.set(id, stdin);
      return { stdout: "", stderr: "" };
    }
    if (argv[0] === "lookup") {
      if (!secrets.has(id)) throw Object.assign(new Error("Not found"), { exitCode: 1, stderr: "" });
      return { stdout: secrets.get(id), stderr: "" };
    }
    throw new Error("Unexpected secret-tool command");
  };
  const make = () => createSecretServiceEncryption({ run, service: "test-service", account: "synthetic-user" });
  return { make, secrets, calls, fail: value => { failure = value; } };
}

test("Linux credentials round-trip through new adapter instance; keys never enter argv", async () => {
  const fake = fakeService();
  const a = fake.make();
  const ciphertext = await a.encrypt("SYNTHETIC_OAUTH_SECRET");
  assert.equal(ciphertext[0], 2);
  assert.equal(ciphertext.includes(Buffer.from("SYNTHETIC_OAUTH_SECRET")), false);
  assert.equal(fake.secrets.size, 1);
  assert.equal(fake.calls[0].argv[0], "store");
  assert.equal(fake.calls[0].inputPresent, true);
  assert.equal(fake.calls.some(x => x.argv.join(" ").includes("SYNTHETIC_OAUTH_SECRET")), false);
  const b = fake.make();
  assert.equal(await b.decrypt(ciphertext), "SYNTHETIC_OAUTH_SECRET");
  const updated = await b.encrypt("UPDATED_SECRET");
  assert.equal(fake.secrets.size, 1, "A new secret-tool store must not overwrite an existing item");
  assert.equal(await fake.make().decrypt(updated), "UPDATED_SECRET");
});

test("missing/locked key cannot be recreated during decrypt", async () => {
  const fake = fakeService();
  const blob = await fake.make().encrypt("TEST_SECRET");
  fake.secrets.clear();
  const before = fake.calls.length;
  await assert.rejects(fake.make().decrypt(blob), /could not read|cannot read/i);
  assert.equal(fake.secrets.size, 0);
  assert.deepEqual(fake.calls.slice(before).map(x => x.argv[0]), ["lookup"]);
});

test("Secret Service unavailable fails closed; no plaintext credential file", async () => {
  const fake = fakeService();
  fake.fail(Object.assign(new Error("No DBus session"), { exitCode: 1, stderr: "Could not connect to Secret Service" }));
  await assert.rejects(fake.make().encrypt("SHOULD_NOT_STORE"), /refusing unencrypted credentials/i);
  assert.equal(fake.secrets.size, 0);
});

test("corrupt stored key is rejected without replacing it", async () => {
  const fake = fakeService();
  const blob = await fake.make().encrypt("SYNTHETIC_ONLY");
  const id = blob.subarray(1, 17).toString("hex");
  fake.secrets.set(id, "corrupted");
  const count = fake.calls.length;
  await assert.rejects(fake.make().decrypt(blob), /invalid encoding/i);
  assert.deepEqual(fake.calls.slice(count).map(x => x.argv[0]), ["lookup"]);
  assert.equal(fake.secrets.get(id), "corrupted");
});

test("tampered AES-GCM ciphertext is rejected", async () => {
  const fake = fakeService();
  const blob = await fake.make().encrypt("TEST_CREDENTIAL");
  const bad = Buffer.from(blob);
  bad[bad.length - 1] ^= 1;
  await assert.rejects(fake.make().decrypt(bad));
  assert.equal(await fake.make().decrypt(blob), "TEST_CREDENTIAL");
});

test("independent first registrations use separate random key IDs, not overwrites", async () => {
  const fake = fakeService();
  const a = await fake.make().encrypt("A");
  const b = await fake.make().encrypt("B");
  assert.notEqual(a.subarray(1, 17).toString("hex"), b.subarray(1, 17).toString("hex"));
  assert.equal(fake.secrets.size, 2);
  assert.equal(await fake.make().decrypt(a), "A");
  assert.equal(await fake.make().decrypt(b), "B");
});
