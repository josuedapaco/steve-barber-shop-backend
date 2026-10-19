import { integer, sqliteTable, text, uniqueIndex } from "drizzle-orm/sqlite-core";
export const appointments = sqliteTable("appointments", {
  id: text("id").primaryKey(),
  barberId: text("barber_id").notNull(),
  serviceId: text("service_id").notNull(),
  date: text("date").notNull(),
  time: text("time").notNull(),
  duration: integer("duration").notNull(),
  customerName: text("customer_name").notNull(),
  customerEmail: text("customer_email").notNull(),
  customerPhone: text("customer_phone").notNull(),
  notes: text("notes").notNull().default(""),
  status: text("status").notNull().default("confirmed"),
  createdAt: text("created_at").notNull(),
});
export const occupiedSlots = sqliteTable("occupied_slots", {
  barberId: text("barber_id").notNull(),
  date: text("date").notNull(),
  time: text("time").notNull(),
  appointmentId: text("appointment_id").notNull(),
}, (table) => [uniqueIndex("slot_unique").on(table.barberId, table.date, table.time)]);

export const staffServiceSettings = sqliteTable("staff_service_settings", {
  staffId: text("staff_id").primaryKey(),
  specialty: text("specialty").notNull(),
  serviceIds: text("service_ids", { mode: "json" }).$type<string[]>().notNull(),
  updatedAt: text("updated_at").notNull(),
});

export const teamMembers = sqliteTable("team_members", {
  id: text("id").primaryKey(),
  name: text("name").notNull(),
  normalizedName: text("normalized_name").notNull().unique(),
  pinSalt: text("pin_salt").notNull(),
  pinHash: text("pin_hash").notNull(),
  sessionSecret: text("session_secret").notNull(),
  createdAt: text("created_at").notNull(),
});
