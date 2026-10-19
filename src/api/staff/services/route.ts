import { getDb } from "../../../db";
import { staffServiceSettings } from "../../../db/schema";
import { getStaffSession } from "../../../lib/staff-auth";
import { getTeamServices, validAssignment, specialtyForServices } from "../../../lib/staff-services";
export async function GET() {
  const session = await getStaffSession();
  if (!session) return Response.json({ error: "Unauthorized" }, { status: 401 });
  if (session.role !== "manager") return Response.json({ error: "Manager access required" }, { status: 403 });
  try { return Response.json({ team: await getTeamServices() }, { headers: { "Cache-Control": "no-store" } }); }
  catch { return Response.json({ error: "Team services are temporarily unavailable." }, { status: 503 }); }
}
export async function POST(request: Request) {
  const session = await getStaffSession();
  if (!session) return Response.json({ error: "Unauthorized" }, { status: 401 });
  if (session.role !== "manager") return Response.json({ error: "Manager access required" }, { status: 403 });
  let input: unknown;
  try { input = await request.json(); } catch { return Response.json({ error: "Invalid request." }, { status: 400 }); }
  if (!validAssignment(input)) return Response.json({ error: "Choose valid services from the barber menu." }, { status: 400 });
  try {
    if (!(await getTeamServices()).some(person => person.staffId === input.staffId)) return Response.json({ error: "Invalid barber" }, { status: 400 });
    const values = { staffId: input.staffId, specialty: specialtyForServices(input.serviceIds), serviceIds: input.serviceIds, updatedAt: new Date().toISOString() };
    await getDb().insert(staffServiceSettings).values(values).onConflictDoUpdate({ target: staffServiceSettings.staffId, set: values });
    return Response.json({ ok: true, team: await getTeamServices() }, { headers: { "Cache-Control": "no-store" } });
  } catch { return Response.json({ error: "Could not save team services." }, { status: 503 }); }
}
