export async function POST() {
  const response = Response.json({ ok: true });
  response.headers.set("Set-Cookie", "atelier_staff=; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=0");
  return response;
}
