import test from "node:test";
import assert from "node:assert/strict";
import { createKeychainKeyReader } from "./keychain-store.mjs";

const fixedKey = Buffer.alloc(32, 11);
const parameters = { keychain: "/usr/bin/security", account: "synthetic-user", service: "synthetic-service" };

test("existing valid encryption key is reused without creating another item", async () => {
  const actions = [];
  const keychainKey = createKeychainKeyReader({ ...parameters, execFileAsync: async (_binary, argv) => {
    actions.push(argv[0]);
    return { stdout: fixedKey.toString("base64") + "\n" };
  }});
  assert.deepEqual(await keychainKey(), fixedKey);
  assert.deepEqual(await keychainKey({createIfMissing: true}), fixedKey);
  assert.deepEqual(actions, ["find-generic-password", "find-generic-password"]);
});

test("a decrypt-only lookup never creates even when the item is missing", async () => {
  const actions = [];
  const keychainKey = createKeychainKeyReader({ ...parameters, execFileAsync: async (_binary, argv) => {
    actions.push(argv[0]);
    throw Object.assign(new Error("not found"), { stderr: "security: The specified item could not be found in the keychain." });
  }});
  await assert.rejects(keychainKey(), /cannot read its Keychain encryption key/i);
  assert.deepEqual(actions, ["find-generic-password"]);
});

test("access denied never triggers key creation or replacement, even when requested", async () => {
  const actions = [];
  const keychainKey = createKeychainKeyReader({ ...parameters, execFileAsync: async (_binary, argv) => {
    actions.push(argv[0]);
    throw Object.assign(new Error("locked"), { stderr: "security: User interaction is not allowed." });
  }});
  await assert.rejects(keychainKey({createIfMissing: true}), /cannot read its Keychain encryption key/i);
  assert.deepEqual(actions, ["find-generic-password"]);
});

test("a missing key may be created for encrypt, but without the destructive -U flag", async () => {
  const actions = [];
  const keychainKey = createKeychainKeyReader({ ...parameters, execFileAsync: async (_binary, argv) => {
    actions.push(argv);
    if (argv[0] === "find-generic-password") {
      throw Object.assign(new Error("missing"), { stderr: "The specified item could not be found in the keychain." });
    }
    if (argv[0] === "add-generic-password") return { stdout: "" };
    throw new Error("unexpected command");
  }});
  const key = await keychainKey({ createIfMissing: true });
  assert.equal(key.length, 32);
  assert.deepEqual(actions.map(a => a[0]), ["find-generic-password", "add-generic-password"]);
  assert.equal(actions[1].includes("-U"), false);
});

test("corrupt existing key must not be replaced", async () => {
  const actions = [];
  const keychainKey = createKeychainKeyReader({ ...parameters, execFileAsync: async (_binary, argv) => {
    actions.push(argv[0]);
    return { stdout: "YmFk" };
  }});
  await assert.rejects(keychainKey({createIfMissing:true}), /invalid length/i);
  assert.deepEqual(actions, ["find-generic-password"]);
});

test("racing insert must fail closed without rewriting an existing item", async () => {
  const actions = [];
  const keychainKey = createKeychainKeyReader({ ...parameters, execFileAsync: async (_binary, argv) => {
    actions.push(argv[0]);
    if (argv[0] === "find-generic-password") {
      throw Object.assign(new Error("missing"), { stderr: "The specified item could not be found in the keychain." });
    }
    throw Object.assign(new Error("duplicate"), { stderr: "The specified item already exists in the keychain." });
  }});
  await assert.rejects(keychainKey({createIfMissing:true}), /duplicate/);
  assert.deepEqual(actions, ["find-generic-password", "add-generic-password"]);
});
