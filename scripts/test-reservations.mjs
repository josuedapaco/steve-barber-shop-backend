import { build } from 'esbuild';
import { readFile, readdir } from 'node:fs/promises';
import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
const nodeRuntime = true;
const testDirectory = nodeRuntime ? await mkdtemp(join(tmpdir(), 'barber-node-test-')) : '';
if (nodeRuntime) { process.env.DATABASE_PATH = join(testDirectory, 'test.sqlite'); process.env.STAFF_PIN = 'test-manager'; process.env.BARBER_PIN_MARCO = 'test-marco'; }

const bundle = await build({
  stdin: { contents: `
    import { database, requestContext } from './src/runtime';
    export const getTestDatabase = () => database;
    import * as appointments from './src/api/appointments/route';
    import * as availability from './src/api/availability/route';
    import * as status from './src/api/staff/status/route';
    import * as staffServices from './src/api/staff/services/route';
    import * as team from './src/api/team/route';
    import * as addStaff from './src/api/staff/team/route';
    import * as staffLogin from './src/api/staff/login/route';
    import { authenticateStaff } from './src/lib/staff-auth';
    export default { fetch(request) { return requestContext.run(request, async () => {
      globalThis.testCookie = request.headers.get('cookie')?.replace('atelier_staff=', '') || '';
      const path = new URL(request.url).pathname;
      if (path === '/test/login') return Response.json(await authenticateStaff('test-manager'));
      if (path === '/test/barber-login') return Response.json(await authenticateStaff('test-marco', 'marco'));
      const routes = { '/api/staff/services': staffServices, '/api/team': team, '/api/staff/team': addStaff, '/api/staff/login': staffLogin, '/api/appointments': appointments, '/api/availability': availability, '/api/staff/status': status };
      return routes[path][request.method](request);
    }); }};
  `, resolveDir: process.cwd(), loader: 'ts' },
  bundle: true, write: false, format: 'esm', platform: nodeRuntime ? 'node' : 'browser',
  external: nodeRuntime ? ['node:*'] : ['cloudflare:workers'],
  plugins: [{ name: 'test-cookies', setup(builder) {

    builder.onResolve({ filter: /^next\/headers$/ }, () => ({ path: 'cookies', namespace: 'test' }));
    builder.onLoad({ filter: /.*/, namespace: 'test' }, () => ({ contents:
      'export async function cookies() { return { get: () => ({ value: globalThis.testCookie }) }; }' }));
  } }],
});
let mf;
if (nodeRuntime) {
  const worker = await import('data:text/javascript;base64,' + Buffer.from(bundle.outputFiles[0].text).toString('base64'));
  mf = { dispatchFetch: (url, options) => worker.default.fetch(new Request(url, options)), getD1Database: () => worker.getTestDatabase(), dispose: async () => { worker.getTestDatabase().close(); await rm(testDirectory, { recursive: true, force: true }); } };
}
let passed = 0, failed = 0;
const date = '2099-06-15';
const base = { barberId: 'marco', serviceId: 'signature', date, time: '10:00',
  name: 'Cliente Ficticio Uno', email: 'cliente1@example.com', phone: '2025550101' };
async function call(path, body, token) {
  const response = await mf.dispatchFetch('http://localhost' + path, {
    method: body === undefined ? 'GET' : 'POST',
    headers: { 'content-type': 'application/json', ...(token ? { cookie: `atelier_staff=${token}` } : {}) },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  return { status: response.status, data: await response.json(), headers: response.headers };
}
async function test(name, fn) {
  try { await fn(); passed++; console.log('PASS', name); }
  catch (error) { failed++; console.error('FAIL', name, error.message); }
}
const book = (changes = {}) => call('/api/appointments', { ...base, ...changes });
const available = (barber = 'marco', service = 'signature') =>
  call(`/api/availability?date=${date}&barber=${barber}&service=${service}`);
try {
  const db = await mf.getD1Database('DB');
  for (const file of (nodeRuntime ? [] : await readdir('drizzle')).filter(f => f.endsWith('.sql')).sort()) {
    for (const sql of (await readFile(`drizzle/${file}`, 'utf8')).split(';').map(s => s.replace('--> statement-breakpoint', '').trim()).filter(Boolean))
      await db.prepare(sql).run();
  }
  let first;
  await test('horarios disponibles antes de reservar', async () => {
    const r = await available(); assert.equal(r.status, 200); assert.ok(r.data.slots.includes('10:00'));
  });
  await test('cliente 1 reserva y sus datos quedan guardados', async () => {
    first = await book(); assert.equal(first.status, 201);
    const row = await db.prepare('SELECT * FROM appointments WHERE id = ?').bind(first.data.id).first();
    assert.equal(row.customer_email, base.email); assert.equal(row.status, 'confirmed');
    assert.equal((await db.prepare('SELECT COUNT(*) AS n FROM occupied_slots WHERE appointment_id = ?').bind(first.data.id).first()).n, 4);
  });
  await test('horarios ocupados desaparecen de disponibilidad', async () => {
    const r = await available(); assert.ok(!r.data.slots.includes('10:00')); assert.ok(!r.data.slots.includes('10:30')); assert.ok(r.data.slots.includes('11:00'));
  });
  await test('cliente 2 no puede duplicar la reserva', async () => assert.equal((await book({ email: 'cliente2@example.com' })).status, 409));
  await test('cliente 2 no puede solapar media hora', async () => assert.equal((await book({ time: '10:30' })).status, 409));
  await test('otro barbero puede atender a la misma hora', async () => assert.equal((await book({ barberId: 'james', name: 'Cliente Ficticio Dos' })).status, 201));
  await test('reserva consecutiva a las 11:00', async () => assert.equal((await book({ time: '11:00' })).status, 201));
  await test('servicio de 75 minutos bloquea todo su intervalo', async () => {
    assert.equal((await book({ time: '13:00', serviceId: 'complete' })).status, 201);
    assert.equal((await book({ time: '14:00', serviceId: 'beard' })).status, 409);
    assert.ok(!(await available()).data.slots.includes('14:00'));
  });
  await test('servicio de 45 minutos se guarda correctamente', async () => assert.equal((await book({ time: '15:00', serviceId: 'beard' })).status, 201));
  for (const [name, change] of [
    ['email inválido', { email: 'invalid' }], ['nombre vacío', { name: '' }],
    ['teléfono corto', { phone: '123' }], ['fecha pasada', { date: '2000-01-01' }],
    ['barbero inexistente', { barberId: 'unknown' }], ['servicio inexistente', { serviceId: 'unknown' }],
    ['fuera de horario', { time: '19:00' }], ['servicio que termina después del cierre', { time: '18:00' }],
    ['notas excesivas', { notes: 'x'.repeat(501) }],
  ]) await test(`rechaza ${name}`, async () => assert.equal((await book(change)).status, 400));
  await test('dos clientes simultáneos: una reserva y un conflicto', async () => {
    const results = await Promise.all([book({ time: '16:00' }), book({ time: '16:00', email: 'cliente3@example.com' })]);
    assert.deepEqual(results.map(r => r.status).sort(), [201, 409]);
    assert.equal((await db.prepare("SELECT COUNT(*) AS n FROM appointments WHERE barber_id = 'marco' AND time = '16:00'").first()).n, 1);
  });
  await test('agenda privada rechaza clientes sin autenticar', async () => assert.equal((await call(`/api/appointments?date=${date}`)).status, 401));
  const { data: login } = await call('/test/login');
  await test('manager ve las reservas ficticias', async () => {
    const r = await call(`/api/appointments?date=${date}`, undefined, login.token);
    assert.equal(r.status, 200); assert.ok(r.data.appointments.some(a => a.id === first.data.id));
  });
  await test('cancelar libera los horarios', async () => {
    assert.equal((await call('/api/staff/status', { id: first.data.id, status: 'cancelled' }, login.token)).status, 200);
    assert.ok((await available()).data.slots.includes('10:00'));
  });
  await test('otro cliente puede reservar la hora cancelada', async () => assert.equal((await book({ name: 'Cliente Después de Cancelación' })).status, 201));

  const { data: barberLogin } = await call('/test/barber-login');
  await test('equipo conserva los tres barberos y servicios originales', async () => {
    const r = await call('/api/team'); assert.equal(r.status, 200); assert.equal(r.data.team.length, 3);
    assert.deepEqual(r.data.team.find(p => p.id === 'marco').serviceIds, ['signature','beard','complete']);
    assert.equal(r.data.team.find(p => p.id === 'marco').role, 'Master Barber');
  });
  const newPerson = { name: 'Barbero Demo', serviceIds: ['beard'], accessCode: 'barber-demo-test-code' };
  let newId, newToken;
  await test('alta y permisos requieren manager', async () => {
    for (const path of ['/api/staff/team','/api/staff/services']) {
      assert.equal((await call(path,newPerson)).status,401);
      assert.equal((await call(path,newPerson,barberLogin.token)).status,403);
    }
  });
  await test('rechaza altas con código débil y servicios inválidos', async () => {
    for (const changes of [{name:''},{accessCode:'123'},{serviceIds:['massage']},{serviceIds:['beard','beard']}])
      assert.equal((await call('/api/staff/team',{...newPerson,...changes},login.token)).status,400);
  });
  await test('manager crea barbero y guarda el código solo como hash', async () => {
    const r=await call('/api/staff/team',newPerson,login.token); assert.equal(r.status,201); newId=r.data.id;
    const stored=await db.prepare('SELECT * FROM team_members WHERE id = ?').bind(newId).first();
    assert.equal(stored.pin_hash.length,64); assert.notEqual(stored.pin_hash,newPerson.accessCode);
    assert.ok(!JSON.stringify(r.data).includes(newPerson.accessCode));
  });
  await test('no permite nombres duplicados ni duplicar barberos originales', async () => {
    for(const name of [' BARBERO   DEMO ', 'Marco Reyes']) assert.equal((await call('/api/staff/team',{...newPerson,name},login.token)).status,409);
  });
  await test('equipo público incluye nuevas altas sin credenciales', async () => {
    const r=await call('/api/team'); assert.equal(r.data.team.length,4); assert.ok(r.data.team.some(p=>p.id===newId));
    for(const secret of ['pinHash','pinSalt','sessionSecret',newPerson.accessCode]) assert.ok(!JSON.stringify(r.data).includes(secret));
  });
  await test('alta recibe reservas solo para servicios autorizados', async () => {
    assert.equal((await available(newId,'signature')).status,403);
    assert.equal((await book({barberId:newId})).status,403);
    assert.equal((await available(newId,'beard')).status,200);
    assert.equal((await book({barberId:newId,serviceId:'beard'})).status,201);
  });
  await test('nuevo barbero inicia sesión y solo consulta su agenda', async () => {
    assert.equal((await call('/api/staff/login',{barberId:newId,pin:'incorrect'})).status,401);
    const r=await call('/api/staff/login',{barberId:newId,pin:newPerson.accessCode});assert.equal(r.status,200);
    newToken=r.headers.get('set-cookie').split('=')[1].split(';')[0];
    const agenda=await call(`/api/appointments?date=${date}&barber=marco`,undefined,newToken);
    assert.equal(agenda.status,200);assert.equal(agenda.data.appointments.length,1); assert.ok(agenda.data.appointments.every(a=>a.barberId===newId));
    assert.equal((await call('/api/staff/status',{id:first.data.id,status:'completed'},newToken)).status,403);
  });
  await test('manager asigna todas las actividades y persiste los permisos', async () => {
    const ids=['signature','beard','complete'];
    assert.equal((await call('/api/staff/services',{staffId:newId,serviceIds:ids},login.token)).status,200);
    for(const service of ids) assert.equal((await available(newId,service)).status,200);
    const stored=await db.prepare('SELECT service_ids FROM staff_service_settings WHERE staff_id = ?').bind(newId).first();assert.deepEqual(JSON.parse(stored.service_ids),ids);
  });
  await test('deshabilitar servicios bloquea reservas sin borrar citas ni acceso', async () => {
    assert.equal((await call('/api/staff/services',{staffId:newId,serviceIds:[]},login.token)).status,200);
    assert.equal((await available(newId,'beard')).status,403);
    assert.equal((await book({barberId:newId,serviceId:'beard',time:'12:00'})).status,403);
    const agenda=await call(`/api/appointments?date=${date}`,undefined,newToken); assert.equal(agenda.data.appointments.length,1);
  });
  await test('permisos persistidos inválidos fallan sin otorgar servicios', async () => {
    await db.prepare("UPDATE staff_service_settings SET service_ids = '[\"unknown\"]' WHERE staff_id = ?").bind(newId).run();
    assert.equal((await available(newId,'beard')).status,503);
  });
  await test('rechaza fecha de calendario inexistente', async () => assert.equal((await book({ date: '2099-02-31' })).status, 400));
} finally {
  await mf.dispose();
}
console.log(`\n${passed} aprobadas, ${failed} fallidas. ${nodeRuntime ? "SQLite Node.js temporal" : "D1 local en memoria"}; sin datos de producción.`);
process.exitCode = failed ? 1 : 0;
