import { authenticateStaff } from "../../../lib/staff-auth";
export async function POST(request: Request) {
  let pin: unknown, barberId: unknown;
  try { ({ pin, barberId } = await request.json() as { pin?: unknown; barberId?: unknown }); }
  catch { return Response.json({ error: "Invalid request." }, { status: 400 }); }
  if (typeof pin !== "string" || (barberId !== undefined && typeof barberId !== "string")) return Response.json({ error: "Invalid request." }, { status: 400 });
  const login = await authenticateStaff(pin, barberId as string | undefined);
  if (!login) return Response.json({ error: "Incorrect access code." }, { status: 401 });
  const response = Response.json({ ok: true, session: login.session });
  response.headers.set("Set-Cookie", `atelier_staff=${login.token}; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=43200`);
  return response;
}
