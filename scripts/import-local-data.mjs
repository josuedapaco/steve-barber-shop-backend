import { DatabaseSync } from 'node:sqlite';
import { resolve } from 'node:path';
import { openDatabase } from '../src/node-database.mjs';
const filename = process.argv[2];
if (!filename) throw new Error('Uso: node scripts/import-local-data.mjs /ruta/a/base-anterior.sqlite');
if (resolve(filename) === resolve(process.env.DATABASE_PATH || './data/barber.sqlite')) throw new Error('Origen y destino deben ser diferentes.');
const source = new DatabaseSync(resolve(filename), { readOnly: true });
const target = openDatabase();
const tables = ['appointments', 'occupied_slots', 'team_members', 'staff_service_settings'];
try {
  for (const name of tables) if ((await target.prepare(`SELECT count(*) AS n FROM ${name}`).first()).n) throw new Error('El destino contiene datos. No se sobrescribe.');
  source.exec('BEGIN');
  const statements = [];
  for (const name of tables) {
    if (!source.prepare("SELECT name FROM sqlite_master WHERE type='table' AND name=?").get(name)) continue;
    for (const row of source.prepare(`SELECT * FROM ${name}`).all()) {
      const columns = Object.keys(row);
      statements.push(target.prepare(`INSERT INTO ${name} (${columns.map(c => '"'+c+'"').join(',')}) VALUES (${columns.map(() => '?').join(',')})`).bind(...Object.values(row)));
    }
  }
  source.exec('COMMIT');
  if (statements.length) await target.batch(statements);
  console.log('Importación finalizada:', (await target.prepare('SELECT count(*) AS n FROM appointments').first()).n, 'citas conservadas.');
} finally { source.close(); target.close(); }
