import { DatabaseSync } from 'node:sqlite';
import { mkdirSync, readdirSync, readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';

// SQLite-backed implementation of the small D1 API used by Drizzle.
// Each batch runs synchronously in one transaction, including slot reservations.
export function openDatabase(filename = process.env.DATABASE_PATH || './data/barber.sqlite') {
  const path = resolve(filename);
  mkdirSync(dirname(path), { recursive: true });
  const sqlite = new DatabaseSync(path);
  sqlite.exec('PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000; PRAGMA foreign_keys=ON;');
  try {
    sqlite.exec('BEGIN IMMEDIATE');
    sqlite.exec('CREATE TABLE IF NOT EXISTS node_migrations (name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)');
    const directory = resolve('drizzle');
    for (const name of readdirSync(directory).filter(name => name.endsWith('.sql')).sort()) {
      if (sqlite.prepare('SELECT name FROM node_migrations WHERE name = ?').get(name)) continue;
      sqlite.exec(readFileSync(resolve(directory, name), 'utf8'));
      sqlite.prepare('INSERT INTO node_migrations VALUES (?, ?)').run(name, new Date().toISOString());
    }
    sqlite.exec('COMMIT');
  } catch (error) { sqlite.exec('ROLLBACK'); sqlite.close(); throw error; }
  class Statement {
    constructor(sql, params = []) { this.sql = sql; this.params = params; }
    bind(...params) { return new Statement(this.sql, params); }
    result() {
      const statement = sqlite.prepare(this.sql);
      if (statement.columns().length) return { success: true, results: statement.all(...this.params), meta: {} };
      const info = statement.run(...this.params);
      return { success: true, results: [], meta: { changes: Number(info.changes), last_row_id: Number(info.lastInsertRowid) } };
    }
    async all() { return this.result(); }
    async run() { return this.result(); }
    async first(column) { const row = this.result().results[0]; return row ? (column ? row[column] : row) : null; }
    async raw() {
      const statement = sqlite.prepare(this.sql);
      statement.setReturnArrays(true);
      return statement.all(...this.params);
    }
  }
  return {
    prepare(sql) { return new Statement(sql); },
    async batch(statements) {
      sqlite.exec('BEGIN IMMEDIATE');
      try { const results = statements.map(statement => statement.result()); sqlite.exec('COMMIT'); return results; }
      catch (error) { sqlite.exec('ROLLBACK'); throw error; }
    },
    close() { sqlite.close(); },
  };
}
