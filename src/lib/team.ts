import { getDb } from "../db";
import { teamMembers } from "../db/schema";
import { barbers } from "./barber";
export type Professional = { id: string; name: string; image: string; initials: string };
export function initialsFor(name: string) {
  return name.trim().split(/\s+/).slice(0, 2).map(word => Array.from(word)[0]).join("").toUpperCase();
}
export async function getProfessionals(): Promise<Professional[]> {
  // Explicitly select public fields: access-code hashes and signing keys must stay server-only.
  const added = await getDb().select({ id: teamMembers.id, name: teamMembers.name }).from(teamMembers).orderBy(teamMembers.createdAt, teamMembers.id);
  return [
    ...barbers.map(({ id, name, image, initials }) => ({ id, name, image, initials })),
    ...added.map(person => ({ ...person, image: "/barber-avatar.svg", initials: initialsFor(person.name) })),
  ];
}
