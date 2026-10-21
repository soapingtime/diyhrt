/*
 * Encryption for forum DMs. This is the only file that touches your keys.
 *
 * Served as-is: no bundler, no minifier, no build step. What your browser runs
 * is what's in this file, so you can check it:
 *
 *   curl -s https://forum.diyhrt.coffee/e2ee/e2ee-core.js | sha384sum
 *   sha384sum e2ee-core.js   # from a clone of the repo
 *
 * Same digest both times means you're running the published code. If they
 * differ, don't send anything sensitive and tell someone.
 *
 * Crypto is libsodium. Nothing here is hand-rolled:
 *   X25519 keypair, crypto_box_easy for messages, argon2id + secretbox to wrap
 *   the private key, blake2b for fingerprints.
 *
 * No forward secrecy yet. Keys are long-term, so passphrase + stored blob
 * decrypts history. Ratchet is planned, hence E2EE_VERSION.
 */

export const E2EE_VERSION = 1;

// argon2id INTERACTIVE. ~64MB, under a second on a phone. Stored per identity
// so we can raise it later without orphaning existing keys.
export const KDF_OPS = 2;
export const KDF_MEM = 67108864;

// Order matters. libsodium-sumo.js defines globalThis.libsodium (the wasm
// core); libsodium-wrappers.js reads that and builds globalThis.sodium. Load
// the wrapper alone and it wraps undefined.
const SODIUM_CORE_URL = "/e2ee/libsodium-sumo.js";
const SODIUM_WRAP_URL = "/e2ee/libsodium-wrappers.js";

let sodiumReady = null;

function loadScript(src) {
  return new Promise((resolve, reject) => {
    const el = document.createElement("script");
    el.src = src;
    el.async = false; // keep execution order
    el.onload = () => resolve();
    el.onerror = () => reject(new Error("could not load " + src));
    document.head.appendChild(el);
  });
}

// UMD builds, so they attach to globalThis rather than exporting.
export function initCrypto() {
  if (sodiumReady) return sodiumReady;
  sodiumReady = (async () => {
    if (typeof window === "undefined") throw new Error("browser only");
    if (!globalThis.sodium) {
      if (!globalThis.libsodium) await loadScript(SODIUM_CORE_URL);
      await loadScript(SODIUM_WRAP_URL);
    }
    const s = globalThis.sodium;
    if (!s) throw new Error("libsodium failed to load");
    await s.ready;
    return s;
  })();
  return sodiumReady;
}

const b64 = (s, buf) => s.to_base64(buf, s.base64_variants.ORIGINAL);
const unb64 = (s, str) => s.from_base64(str, s.base64_variants.ORIGINAL);

// Don't feed this the login password. That one goes to the server to be
// checked, so wrapping the key with it would hand the server the key too.
async function wrapKey(pass, salt, ops, mem) {
  const s = await initCrypto();
  return s.crypto_pwhash(
    s.crypto_secretbox_KEYBYTES,
    pass,
    salt,
    ops,
    mem,
    s.crypto_pwhash_ALG_ARGON2ID13,
  );
}

export async function createIdentity(pass) {
  const s = await initCrypto();
  const kp = s.crypto_box_keypair();
  const salt = s.randombytes_buf(s.crypto_pwhash_SALTBYTES);
  const wk = await wrapKey(pass, salt, KDF_OPS, KDF_MEM);

  const nonce = s.randombytes_buf(s.crypto_secretbox_NONCEBYTES);
  const sealed = s.crypto_secretbox_easy(kp.privateKey, nonce, wk);

  // nonce up front so the whole thing round-trips as one field
  const blob = new Uint8Array(nonce.length + sealed.length);
  blob.set(nonce, 0);
  blob.set(sealed, nonce.length);

  return {
    publicKey: b64(s, kp.publicKey),
    wrappedSecret: b64(s, blob),
    kdfSalt: b64(s, salt),
    kdfOps: KDF_OPS,
    kdfMem: KDF_MEM,
  };
}

// null means wrong passphrase. That's the auth tag doing its job, not a bug.
export async function unlockIdentity(id, pass) {
  const s = await initCrypto();
  try {
    const wk = await wrapKey(pass, unb64(s, id.kdfSalt), id.kdfOps, id.kdfMem);
    const blob = unb64(s, id.wrappedSecret);
    const n = s.crypto_secretbox_NONCEBYTES;
    return s.crypto_secretbox_open_easy(blob.slice(n), blob.slice(0, n), wk);
  } catch {
    return null;
  }
}

export async function sealTo(text, theirPub, mySecret) {
  const s = await initCrypto();
  const nonce = s.randombytes_buf(s.crypto_box_NONCEBYTES);
  const cipher = s.crypto_box_easy(
    s.from_string(text),
    nonce,
    unb64(s, theirPub),
    mySecret,
  );
  return { cipher: b64(s, cipher), nonce: b64(s, nonce) };
}

// null on anything wrong: bad key, tampered blob, truncated. Callers show a
// placeholder for that one message instead of blanking the conversation.
export async function openFrom(msg, theirPub, mySecret) {
  const s = await initCrypto();
  try {
    const out = s.crypto_box_open_easy(
      unb64(s, msg.cipher),
      unb64(s, msg.nonce),
      unb64(s, theirPub),
      mySecret,
    );
    return s.to_string(out);
  } catch {
    return null;
  }
}

// Compare this with someone over a channel you already trust. It's what
// catches the server handing you its own key instead of theirs.
export async function fingerprint(pub) {
  const s = await initCrypto();
  const h = s.crypto_generichash(8, unb64(s, pub), null, "uint8array");
  return Array.from(h)
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("")
    .toUpperCase()
    .replace(/(.{4})/g, "$1 ")
    .trim();
}

// Kept in a variable, not localStorage. Anything persisted can be read back
// later by any script that gets to run on this origin. This dies with the tab.
let unlocked = null;

export function setUnlockedKey(k) {
  unlocked = k;
}
export function getUnlockedKey() {
  return unlocked;
}
export function isUnlocked() {
  return unlocked !== null;
}
export function lock() {
  if (unlocked) unlocked.fill(0);
  unlocked = null;
}
