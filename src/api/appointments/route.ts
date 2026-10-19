import { getProfessionals } from "../../lib/team";
import { canPerform } from "../../lib/staff-services";
import { getDb } from "../../db";
import { appointments, occupiedSlots } from "../../db/schema";
import { and, eq, ne } from "drizzle-orm";
import { isCalendarDate, minutes, nyToday, services, times } from "../../lib/barber";
import { getStaffSession } from "../../lib/staff-auth";
export async function GET(request: Request) {
  const session = await getStaffSession();
  if (!session) return Response.json({ error: "Unauthorized" }, { status: 401 });
  const date = new URL(request.url).searchParams.get("date") || nyToday();
  if (!isCalendarDate(date)) return Response.json({ error: "Invalid date" }, { status: 400 });
  const requestedBarber = new URL(request.url).searchParams.get("barber") || "";
  try {
    const team = await getProfessionals();
    if (session.role === "manager" && requestedBarber && !team.some(person => person.id === requestedBarber)) return Response.json({ error: "Invalid barber" }, { status: 400 });
    const conditions = [eq(appointments.date, date)];
    if (session.role === "barber") conditions.push(eq(appointments.barberId, session.barberId));
    else if (requestedBarber) conditions.push(eq(appointments.barberId, requestedBarber));
    const rows = await getDb().select().from(appointments).where(and(...conditions)).orderBy(appointments.time);
    return Response.json({ appointments: rows, session });
  } catch { return Response.json({ error: "Appointments are temporarily unavailable." }, { status: 503 }); }
}
export async function POST(request: Request) {
  let input: Record<string, unknown>;
  try { input = await request.json(); } catch { return Response.json({ error: "Invalid request." }, { status: 400 }); }
  const barberId = String(input.barberId || ""), serviceId = String(input.serviceId || "");
  const date = String(input.date || ""), time = String(input.time || "");
  const customerName = String(input.name || "").trim(), customerEmail = String(input.email || "").trim();
  const customerPhone = String(input.phone || "").trim(), notes = String(input.notes || "").trim();
  const service = services.find(s => s.id === serviceId);
  if (!barberId || !service || !isCalendarDate(date) || date < nyToday() || !times.includes(time) || minutes(time) + service.duration > 18 * 60 + 30 || customerName.length < 2 || customerName.length > 80 || !/^\S+@\S+\.\S+$/.test(customerEmail) || customerEmail.length > 120 || customerPhone.length < 7 || customerPhone.length > 25 || notes.length > 500)
    return Response.json({ error: "Please check your reservation details." }, { status: 400 });
  if (date === nyToday()) {
    const now = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date());
    if (minutes(time) <= minutes(now) + 30) return Response.json({ error: "That time is no longer available." }, { status: 409 });
  }
  try {
    if (!(await getProfessionals()).some(person => person.id === barberId)) return Response.json({ error: "Invalid barber" }, { status: 400 });
    if (!(await canPerform(barberId, serviceId))) return Response.json({ error: "This professional is not authorized for this service." }, { status: 403 });
    const db = getDb();
    const booked = await db.select().from(appointments).where(and(eq(appointments.date, date), eq(appointments.barberId, barberId), ne(appointments.status, "cancelled")));
    if (booked.some(b => minutes(time) < minutes(b.time) + b.duration && minutes(b.time) < minutes(time) + service.duration))
      return Response.json({ error: "That time was just taken. Please choose another." }, { status: 409 });
    const id = crypto.randomUUID();
    const occupied = Array.from({ length: service.duration / 15 }, (_, i) => {
      const total = minutes(time) + i * 15;
      return { barberId, date, time: `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`, appointmentId: id };
    });
    await db.batch([
      db.insert(appointments).values({ id, barberId, serviceId, date, time, duration: service.duration, customerName, customerEmail, customerPhone, notes, status: "confirmed", createdAt: new Date().toISOString() }),
      db.insert(occupiedSlots).values(occupied),
    ]);
    return Response.json({ id, date, time, barberId, serviceId }, { status: 201 });
  } catch (error) {
    if (String(error).includes("UNIQUE") || String(error).includes("constraint"))
      return Response.json({ error: "That time was just taken. Please choose another." }, { status: 409 });
    return Response.json({ error: "We could not save your reservation. Please try again." }, { status: 503 });
  }
}
