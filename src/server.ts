import { createServer } from 'node:http';
import { requestContext } from './runtime';
import * as appointments from './api/appointments/route';
import * as availability from './api/availability/route';
import * as team from './api/team/route';
import * as login from './api/staff/login/route';
import * as logout from './api/staff/logout/route';
import * as status from './api/staff/status/route';
import * as dashboard from './api/staff/dashboard/route';
import * as services from './api/staff/services/route';
import * as staffTeam from './api/staff/team/route';
const routes: Record<string, Record<string, (request: Request) => Promise<Response>>> = {
  '/api/appointments': appointments, '/api/availability': availability, '/api/team': team,
  '/api/staff/login': login, '/api/staff/logout': logout, '/api/staff/status': status,
  '/api/staff/dashboard': dashboard, '/api/staff/services': services, '/api/staff/team': staffTeam,
};
const origin = process.env.PUBLIC_ORIGIN || 'https://stevesbarbershopny.com';
if (!process.env.STAFF_PIN || process.env.STAFF_PIN.length < 12) throw new Error('STAFF_PIN must contain at least 12 characters');
createServer(async (incoming, outgoing) => {
  try {
    const url = new URL(incoming.url || '/', origin);
    let response: Response;
    if (url.pathname === '/api/health' && incoming.method === 'GET') response = Response.json({ status: 'ok' });
    else {
      const route = routes[url.pathname];
      const handler = route?.[incoming.method || 'GET'];
      if (!route) response = Response.json({ error: 'Not found' }, { status: 404 });
      else if (!handler) response = Response.json({ error: 'Method not allowed' }, { status: 405, headers: { Allow: Object.keys(route).join(', ') } });
      else if (incoming.method === 'POST' && incoming.headers.origin && incoming.headers.origin !== origin) response = Response.json({ error: 'Origin not allowed' }, { status: 403 });
      else {
        const chunks: Buffer[] = []; let size = 0;
        for await (const chunk of incoming) { size += chunk.length; if (size > 65536) { outgoing.writeHead(413); outgoing.end(); return; } chunks.push(Buffer.from(chunk)); }
        const headers = new Headers();
        for (const [key, value] of Object.entries(incoming.headers)) if (value) headers.set(key, Array.isArray(value) ? value.join(', ') : value);
        const request = new Request(url, { method: incoming.method, headers, ...(incoming.method === 'POST' ? { body: Buffer.concat(chunks) } : {}) });
        response = await requestContext.run(request, () => handler(request));
      }
    }
    outgoing.writeHead(response.status, { ...Object.fromEntries(response.headers), 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' });
    outgoing.end(Buffer.from(await response.arrayBuffer()));
  } catch (error) {
    const badRequest = error instanceof SyntaxError;
    if (!badRequest) console.error('Request failed:', error instanceof Error ? error.message : 'Unknown error');
    outgoing.writeHead(badRequest ? 400 : 500, { 'Content-Type': 'application/json' }); outgoing.end(JSON.stringify({ error: badRequest ? 'Invalid request' : 'Internal server error' }));
  }
}).listen(Number(process.env.PORT || 3000), process.env.HOST || '0.0.0.0', () => console.log('Backend listening on port '+(process.env.PORT || 3000)));
