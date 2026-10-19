import { services } from "./barber";
type Appointment = { id: string; date: string; time: string; status: string; serviceId: string; barberId: string; customerName: string; customerEmail: string; customerPhone: string };
export function managerDashboard(rows: Appointment[], today: string) {
  const start = new Date(`${today}T12:00:00Z`);
  start.setUTCDate(start.getUTCDate() - (start.getUTCDay() + 6) % 7);
  const week = Array.from({ length: 7 }, (_, index) => {
    const day = new Date(start); day.setUTCDate(day.getUTCDate() + index);
    return { date: day.toISOString().slice(0, 10), reserved: 0, completed: 0, cancelled: 0 };
  });
  const clients = new Map<string, { name: string; email: string; phone: string; visits: Appointment[]; upcoming: Appointment[] }>();
  for (const row of rows) {
    const day = week.find(day => day.date === row.date);
    const price = services.find(service => service.id === row.serviceId)?.price || 0;
    if (day) {
      if (row.status === "cancelled") day.cancelled += price;
      else if (row.status === "confirmed") day.reserved += price;
      if (row.status === "completed") day.completed += price;
    }
    const key = row.customerEmail.trim().toLowerCase();
    const client = clients.get(key) || { name: row.customerName, email: row.customerEmail, phone: row.customerPhone, visits: [], upcoming: [] };
    if (row.status === "completed") client.visits.push(row);
    if (row.status === "confirmed" && row.date >= today) client.upcoming.push(row);
    clients.set(key, client);
  }
  for (const client of clients.values()) {
    client.visits.sort((a, b) => `${b.date} ${b.time}`.localeCompare(`${a.date} ${a.time}`));
    client.upcoming.sort((a, b) => `${a.date} ${a.time}`.localeCompare(`${b.date} ${b.time}`));
  }
  const serviceDemand = services.map(service => {
    const bookings = rows.filter(row => row.serviceId === service.id && (row.status === "confirmed" || row.status === "completed"));
    return { id: service.id, name: service.name, count: bookings.length,
      completed: bookings.filter(row => row.status === "completed").length,
      reserved: bookings.filter(row => row.status === "confirmed").length };
  }).sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
  const totalRequests = serviceDemand.reduce((total, service) => total + service.count, 0);
  return { week, serviceDemand, totalRequests, clients: Array.from(clients.values()).sort((a, b) => a.name.localeCompare(b.name)) };
}
export type ManagerDashboard = ReturnType<typeof managerDashboard>;
