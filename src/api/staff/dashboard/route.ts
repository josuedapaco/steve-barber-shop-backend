import { getDb } from "../../../db";
import { appointments } from "../../../db/schema";
import { getStaffSession } from "../../../lib/staff-auth";
import { nyToday } from "../../../lib/barber";
import { managerDashboard } from "../../../lib/manager-dashboard";
export async function GET() {
  const session = await getStaffSession();
  if (!session) return Response.json({ error: "Unauthorized" }, { status: 401 });
  if (session.role !== "manager") return Response.json({ error: "Manager access required" }, { status: 403 });
  try {
    const rows = await getDb().select().from(appointments).orderBy(appointments.date, appointments.time);
    return Response.json(managerDashboard(rows, nyToday()), { headers: { "Cache-Control": "no-store" } });
  } catch {
    return Response.json({ error: "No se pudo cargar el resumen del manager." }, { status: 503 });
  }
}
