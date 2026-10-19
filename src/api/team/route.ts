import { getTeamServices } from "../../lib/staff-services";
export async function GET() {
  try { return Response.json({ team: await getTeamServices() }, { headers: { "Cache-Control": "no-store" } }); }
  catch { return Response.json({ error: "Team services are temporarily unavailable." }, { status: 503 }); }
}
