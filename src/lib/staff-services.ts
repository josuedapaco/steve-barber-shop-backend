import { getDb } from "../db";
import { staffServiceSettings } from "../db/schema";
import { barbers, services } from "./barber";
import { getProfessionals, type Professional } from "./team";
export type StaffServices = { staffId: string; serviceIds: string[] };
export function specialtyForServices(_serviceIds: string[]) { return "barber" as const; }
export type TeamMember = StaffServices & Professional & { role: string; specialty: "barber" };
export function validAssignment(value: unknown): value is StaffServices {
  if (!value || typeof value !== "object") return false;
  const row = value as StaffServices;
  return typeof row.staffId === "string" && /^[a-zA-Z0-9_-]{1,80}$/.test(row.staffId)
    && Array.isArray(row.serviceIds)
    && new Set(row.serviceIds).size === row.serviceIds.length
    && row.serviceIds.every(id => typeof id === "string" && services.some(service => service.id === id));
}
export async function getTeamServices(): Promise<TeamMember[]> {
  const people = await getProfessionals();
  const rows = await getDb().select().from(staffServiceSettings);
  return people.map(person => {
    const saved = rows.find(row => row.staffId === person.id);
    const seed = barbers.find(row => row.id === person.id);
    const assignment = saved || { staffId: person.id, specialty: "barber", serviceIds: seed ? services.map(service => service.id) : [] };
    // Bad persisted configuration must never silently grant services.
    if (!validAssignment(assignment)) throw new Error("Invalid staff service configuration");
    const specialty = specialtyForServices(assignment.serviceIds);
    return { ...person, staffId: person.id, specialty, serviceIds: assignment.serviceIds,
      role: seed?.role || "Barber" };
  });
}
export async function canPerform(staffId: string, serviceId: string) {
  const team = await getTeamServices();
  return team.some(person => person.staffId === staffId && person.serviceIds.includes(serviceId));
}
