import { getProfessionals } from "../../lib/team";
import { canPerform } from "../../lib/staff-services";
import { getDb } from "../../db";
import { appointments } from "../../db/schema";
import { and, eq, ne } from "drizzle-orm";
import { isCalendarDate, minutes, nyToday, services, times } from "../../lib/barber";
export async function GET(request: Request) {
  const url = new URL(request.url);
  const date = url.searchParams.get("date") || "", barberId = url.searchParams.get("barber") || "";
  const service = services.find(s => s.id === url.searchParams.get("service"));
  if (!isCalendarDate(date) || date < nyToday() || !barberId || !service)
    return Response.json({ error: "Choose a valid barber, service and date." }, { status: 400 });
  try {
    if (!(await getProfessionals()).some(person => person.id === barberId)) return Response.json({ error: "Invalid barber" }, { status: 400 });
    if (!(await canPerform(barberId, service.id))) return Response.json({ error: "This professional is not authorized for this service." }, { status: 403 });
    const booked = await getDb().select().from(appointments).where(and(eq(appointments.date, date), eq(appointments.barberId, barberId), ne(appointments.status, "cancelled")));
    const slots = times.filter(time => {
      const start = minutes(time);
      if (start + service.duration > 18 * 60 + 30) return false;
      if (date === nyToday()) {
        const now = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date());
        if (start <= minutes(now) + 30) return false;
      }
      return !booked.some(b => start < minutes(b.time) + b.duration && minutes(b.time) < start + service.duration);
    });
    return Response.json({ slots });
  } catch { return Response.json({ error: "Availability is temporarily unavailable." }, { status: 503 }); }
}
