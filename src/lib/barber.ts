export const barbers = [
  { id: "marco", name: "Marco Reyes", role: "Master Barber", image: "https://images.unsplash.com/photo-1506794778202-cad84cf45f1d?w=720&q=85&fit=crop", initials: "MR" },
  { id: "james", name: "James Cole", role: "Senior Barber", image: "https://images.unsplash.com/photo-1500648767791-00dcc994a43e?w=720&q=85&fit=crop", initials: "JC" },
  { id: "andre", name: "André Laurent", role: "Grooming Specialist", image: "https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=720&q=85&fit=crop", initials: "AL" },
];
export const services = [
  { id: "signature", name: "Signature Haircut", price: 75, duration: 60, detail: "Consultation, precision cut & styling" },
  { id: "beard", name: "Beard Ritual", price: 50, duration: 45, detail: "Shape, hot towel & finishing oil" },
  { id: "complete", name: "The Complete", price: 115, duration: 75, detail: "Signature cut & beard ritual" },
];
export const times = Array.from({ length: 17 }, (_, i) => `${String(10 + Math.floor(i / 2)).padStart(2, "0")}:${i % 2 ? "30" : "00"}`);
export function minutes(time: string) { const [h, m] = time.split(":").map(Number); return h * 60 + m; }
export function isCalendarDate(date: string) {
  return /^\d{4}-\d{2}-\d{2}$/.test(date) && !Number.isNaN(Date.parse(date + "T12:00:00Z")) && new Date(date + "T12:00:00Z").toISOString().slice(0, 10) === date;
}
export function nyToday() {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
}
