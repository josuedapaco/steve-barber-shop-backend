import { AsyncLocalStorage } from 'node:async_hooks';
import { openDatabase } from './node-database.mjs';
export const database = openDatabase();
export const env = process.env;
export const requestContext = new AsyncLocalStorage<Request>();
export async function cookies() {
  const raw = requestContext.getStore()?.headers.get('cookie') || '';
  return { get(name: string) { const entry = raw.split(';').map(v => v.trim()).find(v => v.startsWith(name+'=')); return entry ? { value: entry.slice(name.length + 1) } : undefined; } };
}
