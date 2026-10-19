import { eq } from "drizzle-orm";
import { getDb } from "../../../db";
import { appointments, occupiedSlots } from "../../../db/schema";
import { getStaffSession } from "../../../lib/staff-auth";
export async function POST(request: Request) {
  const session = await getStaffSession();
  if (!session) return Response.json({ error: "Unauthorized" }, { status: 401 });
  const { id, status } = (await request.json()) as { id?: string; status?: string };
  if (typeof id !== "string" || (status !== "completed" && status !== "cancelled")) return Response.json({ error: "Invalid update" }, { status: 400 });
  try {
    const db = getDb();
    const [appointment] = await db.select({ barberId: appointments.barberId }).from(appointments).where(eq(appointments.id, id)).limit(1);
    if (!appointment) return Response.json({ error: "Appointment not found." }, { status: 404 });
    if (session.role === "barber" && appointment.barberId !== session.barberId)
      return Response.json({ error: "You can only update your own appointments." }, { status: 403 });
    if (status === "cancelled") await db.batch([
      db.update(appointments).set({ status }).where(eq(appointments.id, id)),
      db.delete(occupiedSlots).where(eq(occupiedSlots.appointmentId, id)),
    ]);
    else await db.update(appointments).set({ status }).where(eq(appointments.id, id));
    return Response.json({ ok: true });
  } catch { return Response.json({ error: "Could not update this appointment." }, { status: 503 }); }
}
