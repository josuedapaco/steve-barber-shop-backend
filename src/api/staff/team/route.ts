import { getDb } from "../../../db";
import { teamMembers, staffServiceSettings } from "../../../db/schema";
import { getStaffSession } from "../../../lib/staff-auth";
import { getProfessionals } from "../../../lib/team";
import { getTeamServices, validAssignment, specialtyForServices } from "../../../lib/staff-services";
import { hashAccessCode } from "../../../lib/access-codes";
export async function POST(request: Request) {
  const session = await getStaffSession();
  if (!session) return Response.json({ error: "Unauthorized" }, { status: 401 });
  if (session.role !== "manager") return Response.json({ error: "Manager access required" }, { status: 403 });
  let input: Record<string, unknown>;
  try {
    const body = await request.json();
    if (!body || typeof body !== "object" || Array.isArray(body)) throw new Error("Invalid body");
    input = body as Record<string, unknown>;
  } catch { return Response.json({ error: "Invalid request." }, { status: 400 }); }
  const name = typeof input.name === "string" ? input.name.trim().replace(/\s+/g, " ") : "";
  const accessCode = typeof input.accessCode === "string" ? input.accessCode : "";
  if (name.length < 2 || name.length > 80 || /[\u0000-\u001f\u007f]/.test(name) || accessCode.length < 8 || accessCode.length > 64 || !accessCode.trim())
    return Response.json({ error: "Enter a name (2–80 characters) and an access code (8–64 characters)." }, { status: 400 });
  const id = crypto.randomUUID();
  const assignment = { staffId: id, serviceIds: input.serviceIds };
  if (!validAssignment(assignment)) return Response.json({ error: "Choose valid services from the barber menu." }, { status: 400 });
  try {
    const normalizedName = name.toLocaleLowerCase("en-US");
    if ((await getProfessionals()).some(person => person.name.toLocaleLowerCase("en-US") === normalizedName))
      return Response.json({ error: "A professional with this name already exists." }, { status: 409 });
    const pinSalt = crypto.randomUUID();
    const pinHash = await hashAccessCode(accessCode, pinSalt);
    const createdAt = new Date().toISOString();
    await getDb().batch([
      getDb().insert(teamMembers).values({ id, name, normalizedName, pinSalt, pinHash, sessionSecret: crypto.randomUUID(), createdAt }),
      getDb().insert(staffServiceSettings).values({ ...assignment, specialty: specialtyForServices(assignment.serviceIds), updatedAt: createdAt }),
    ]);
    return Response.json({ id, team: await getTeamServices() }, { status: 201, headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    if (String(error).includes("UNIQUE")) return Response.json({ error: "A professional with this name already exists." }, { status: 409 });
    return Response.json({ error: "Could not add this professional." }, { status: 503 });
  }
}
