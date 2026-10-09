import { randomBytes } from "node:crypto";

// Only a verified missing Keychain item permits creation. A read that failed
// because of access denial, a locked Keychain, corruption, or an OS error must
// never rotate an existing encryption key.
export function createKeychainKeyReader({ execFileAsync, keychain, account, service }) {
  return async function keychainKey({ createIfMissing = false } = {}) {
    let stdout;
    try {
      ({ stdout } = await execFileAsync(
        keychain,
        ["find-generic-password", "-a", account, "-s", service, "-w"],
        { encoding: "utf8" }
      ));
    } catch (error) {
      const diagnostic = String(error?.stderr || error?.message || "");
      const notFound = /the specified item could not be found in the keychain|errsecitemnotfound/i.test(diagnostic);
      if (!createIfMissing || !notFound) {
        throw new Error(
          "Claudex cannot read its Keychain encryption key; existing credentials were not changed. Check Keychain access in this process.",
          { cause: error }
        );
      }
      const key = randomBytes(32);
      // No -U: creation MUST fail if an item unexpectedly exists, including a
      // race with another process. Updating would destroy encrypted profiles.
      await execFileAsync(
        keychain,
        ["add-generic-password", "-a", account, "-s", service, "-w", key.toString("base64")],
        { encoding: "utf8" }
      );
      return key;
    }

    const key = Buffer.from(stdout.trim(), "base64");
    if (key.length !== 32) {
      throw new Error("Claudex Keychain encryption key has an invalid length; refusing to replace it.");
    }
    return key;
  };
}
