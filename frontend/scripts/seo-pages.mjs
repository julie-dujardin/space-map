// Writes the export's SEO page records into the built site's static assets, one
// file per page, where the Worker reads them (src/lib/seo/meta.ts). Runs after
// `vite build`; the records then show the export as it was at build time.
//
// Usage: node scripts/seo-pages.mjs [data origin, default https://static.spacemap.co]
import { mkdir, rm, writeFile } from 'node:fs/promises';
import { dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { gunzipSync } from 'node:zlib';

const origin = (process.argv[2] ?? 'https://static.spacemap.co').replace(/\/$/, '');
const out = fileURLToPath(new URL('../.svelte-kit/cloudflare/_seo/', import.meta.url));

async function get(path) {
	const res = await fetch(`${origin}${path}`);
	if (!res.ok) throw new Error(`${origin}${path} returned ${res.status} ${res.statusText}`);
	return res;
}

const [metadata, pages] = await Promise.all([
	get('/v1/metadata.json').then((res) => res.json()),
	get('/v1/seo/pages.json.gz').then(async (res) =>
		JSON.parse(gunzipSync(Buffer.from(await res.arrayBuffer())).toString())
	)
]);
// The token of the images the records name, as the bundles' readers get it.
const v = metadata.versions?.images;

await rm(out, { recursive: true, force: true });
const dirs = new Set();
for (const [key, record] of Object.entries(pages)) {
	const file = `${out}${key}.json`;
	const dir = dirname(file);
	if (!dirs.has(dir)) {
		await mkdir(dir, { recursive: true });
		dirs.add(dir);
	}
	await writeFile(file, JSON.stringify({ v, ...record }));
}
console.log(`seo-pages: ${Object.keys(pages).length} records from ${origin} in ${out}`);
