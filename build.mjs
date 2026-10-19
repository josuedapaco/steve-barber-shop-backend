import { build } from 'esbuild';
await build({ entryPoints: ['src/server.ts'], outfile: 'dist/server.mjs', bundle: true, platform: 'node', format: 'esm', target: 'node24', packages: 'external', sourcemap: true });
