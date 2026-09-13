/** Anonymous identity is a server-issued signed cookie, never a caller-supplied identity header. */
export const VISITOR_COOKIE = "fh_visitor";
export const VISITOR_HEADER = "X-Disclosure-Visitor";
export const VISITOR_MAX_AGE = 30 * 24 * 60 * 60;
const UUID = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
const TOKEN = new RegExp(`^v1\\.(${UUID})\\.(\\d{10})\\.([0-9a-f]{64})$`);
const bytes = new TextEncoder();
async function signingKey(secret: string) { return crypto.subtle.importKey("raw", bytes.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign", "verify"]); }
const payload = (id: string, expires: number) => bytes.encode(`disclosure-visitor:v1:${id}:${expires}`);
export async function issueVisitor(secret: string, now = Math.floor(Date.now() / 1000)): Promise<{ id: string; token: string }> {
  if (!secret) throw new Error("Visitor identity needs the gateway API key");
  const id = crypto.randomUUID();
  const expires = now + VISITOR_MAX_AGE;
  const signature = await crypto.subtle.sign("HMAC", await signingKey(secret), payload(id, expires));
  const mac = Array.from(new Uint8Array(signature), (b) => b.toString(16).padStart(2, "0")).join("");
  return { id, token: `v1.${id}.${expires}.${mac}` };
}
export async function verifyVisitor(token: string | undefined, secret: string, now = Math.floor(Date.now() / 1000)): Promise<string | null> {
  if (!token || !secret) return null;
  const match = TOKEN.exec(token);
  if (!match) return null;
  const [, id, rawExpiry, mac] = match;
  const expires = Number(rawExpiry);
  if (expires <= now || expires > now + VISITOR_MAX_AGE + 60) return null;
  const signature = Uint8Array.from(mac.match(/../g)!, (hex) => parseInt(hex, 16));
  return await crypto.subtle.verify("HMAC", await signingKey(secret), signature, payload(id, expires)) ? id : null;
}
