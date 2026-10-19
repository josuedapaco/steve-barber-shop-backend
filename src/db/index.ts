import { drizzle } from "drizzle-orm/d1";
import { database } from "../runtime";
import * as schema from "./schema";
export function getDb() { return drizzle(database as unknown as D1Database, { schema }); }
