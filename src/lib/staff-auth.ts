import { env, cookies } from "../runtime";
import { barbers } from "./barber";
import { getDb } from "../db";
import { teamMembers } from "../db/schema";
import { eq } from "drizzle-orm";
import { hashAccessCode, equalDigest } from "./access-codes";
const encoder = new TextEncoder();
export type StaffSession =
  | { role: "manager"; barberId: null }
  | { role: "barber"; barberId: string };
type StaffEnvironment = { STAFF_PIN?: string; [key: string]: string | undefined };
async function signature(value: string, secret: string) {
  const key = await crypto.subtle.importKey("raw", encoder.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const bytes = new Uint8Array(await crypto.subtle.sign("HMAC", key, encoder.encode(value)));
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}
async function pinFor(session: StaffSession) {
  if (session.role === "barber" && !barbers.some(person => person.id === session.barberId)) {
    const [person] = await getDb().select().from(teamMembers).where(eq(teamMembers.id, session.barberId)).limit(1);
    return person?.sessionSecret || "";
  }
  const variables = env as unknown as StaffEnvironment;
  return session.role === "manager"
    ? variables.STAFF_PIN || ""
    : variables[`BARBER_PIN_${session.barberId.toUpperCase()}`] || "";
}
function tokenPayload(session: StaffSession, expiresAt: number) {
  return `${session.role}.${session.barberId ?? "all"}.${expiresAt}`;
}
async function makeToken(session: StaffSession, secret: string) {
  const expiresAt = Date.now() + 12 * 60 * 60 * 1000;
  const payload = tokenPayload(session, expiresAt);
  return `${payload}.${await signature(payload, secret)}`;
}
export async function authenticateStaff(pin: string, barberId?: string) {
  if (typeof pin !== "string" || pin.length > 64 || (barberId !== undefined && (typeof barberId !== "string" || !barberId))) return null;
  if (barberId && !barbers.some(person => person.id === barberId)) {
    const [person] = await getDb().select().from(teamMembers).where(eq(teamMembers.id, barberId)).limit(1);
    if (!person || !equalDigest(await hashAccessCode(pin, person.pinSalt), person.pinHash)) return null;
    const session: StaffSession = { role: "barber", barberId };
    return { session, token: await makeToken(session, person.sessionSecret) };
  }
  const session: StaffSession = barberId
    ? { role: "barber", barberId }
    : { role: "manager", barberId: null };
  const secret = await pinFor(session);
  if (!secret || pin !== secret) return null;
  return { session, token: await makeToken(session, secret) };
}
export async function getStaffSession(): Promise<StaffSession | null> {
  const [role, subject, rawExpires, digest] = ((await cookies()).get("atelier_staff")?.value || "").split(".");
  const session: StaffSession | null = role === "manager" && subject === "all"
    ? { role: "manager", barberId: null }
    : role === "barber" && /^[a-zA-Z0-9_-]{1,80}$/.test(subject || "")
      ? { role: "barber", barberId: subject }
      : null;
  const expiresAt = Number(rawExpires);
  if (!session || !Number.isSafeInteger(expiresAt) || expiresAt < Date.now() || !digest) return null;
  const secret = await pinFor(session);
  if (!secret) return null;
  const payload = tokenPayload(session, expiresAt);
  return equalDigest(await signature(payload, secret), digest) ? session : null;
}
