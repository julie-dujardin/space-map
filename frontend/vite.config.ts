/// <reference types="vitest/config" />
import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { paraglideVitePlugin } from '@inlang/paraglide-js';
import { paraglideLocaleSplit } from './paraglide-locale-split';
import { defineConfig, type Plugin, type ProxyOptions } from 'vite';
import { fileURLToPath } from 'node:url';
import { createReadStream, readFileSync, statSync } from 'node:fs';
import { join, normalize, resolve, sep } from 'node:path';
import { parseEnv } from 'node:util';

// The dev proxy rewrites PUBLIC_*_URL in process.env, and vite restarts this
// config in-process when .env or this file changes. Stash what the first load
// saw so a restart does not read its own rewrite back as the configured origin
// and silently fall back to the local export.
const STASH = 'SM_DEV_PROXY_ORIGINAL_ENV';
const REWRITTEN = ['PUBLIC_DATA_URL', 'PUBLIC_IMAGES_URL', 'PUBLIC_LIVE_URL'] as const;
const stashed: Record<string, string | null> = JSON.parse(process.env[STASH] ?? '{}');

// satellite.js's optional WASM runtime: nothing calls it, and bundled it is a
// 310 kB chunk with a top-level await.
const noWasm = fileURLToPath(new URL('./src/lib/math/orbit/no-wasm.ts', import.meta.url));

export default defineConfig(({ command, mode }) => {
	// Vite's own loadEnv lets process.env shadow the .env files; parse them off
	// disk so the stash above is the only source of shadowing.
	const fileEnv: Record<string, string> = {};
	for (const file of ['.env', '.env.local', `.env.${mode}`, `.env.${mode}.local`]) {
		try {
			Object.assign(fileEnv, parseEnv(readFileSync(file, 'utf8')));
		} catch {
			// No such .env file.
		}
	}
	const envVar = (key: string) =>
		(key in stashed ? (stashed[key] ?? undefined) : process.env[key]) ?? fileEnv[key];

	// An absolute PUBLIC_DATA_URL (e.g. https://static.spacemap.co) goes through
	// the dev proxy: the browser keeps hitting /data (same-origin, no preflight)
	// while the proxy fetches from the remote without forwarding Origin.
	const configuredDataUrl = envVar('PUBLIC_DATA_URL') ?? '/data';
	const isRemoteDataUrl = /^https?:\/\//i.test(configuredDataUrl);
	const localDataTarget = envVar('DATA_SERVER_URL') ?? 'http://localhost:8080';
	const dataTarget = isRemoteDataUrl ? configuredDataUrl : localDataTarget;

	// Images are their own export project on their own origin, so a remote data
	// origin does not carry them; they get a proxy of their own rather than
	// following /data to a host that would 404 every file.
	const configuredImagesUrl =
		envVar('PUBLIC_IMAGES_URL') ??
		(isRemoteDataUrl ? 'https://images.spacemap.co' : configuredDataUrl);
	const isRemoteImagesUrl = /^https?:\/\//i.test(configuredImagesUrl);

	// The live feed is a third origin. Unset in dev it is the sibling directory
	// the tracking poller writes, served straight off disk; a build keeps the
	// host default.
	const configuredLiveUrl = envVar('PUBLIC_LIVE_URL');
	const isRemoteLiveUrl =
		configuredLiveUrl !== undefined && /^https?:\/\//i.test(configuredLiveUrl);
	const localLiveDir = envVar('LIVE_DIR') ?? resolve('../../space-map-live');

	// Only the dev server has a proxy to point at; a build must bake the real
	// origins into the bundle or every fetch 404s once deployed.
	if (command === 'serve') {
		const originals = Object.fromEntries(REWRITTEN.map((k) => [k, process.env[k] ?? null]));
		process.env[STASH] = JSON.stringify({ ...originals, ...stashed });
		if (isRemoteDataUrl) process.env.PUBLIC_DATA_URL = '/data';
		if (isRemoteImagesUrl) process.env.PUBLIC_IMAGES_URL = '/images';
		if (isRemoteLiveUrl || configuredLiveUrl === undefined) process.env.PUBLIC_LIVE_URL = '/live';
	}

	return {
		resolve: {
			alias: {
				'#wasm-single-thread': noWasm,
				'#wasm-multi-thread': noWasm
			}
		},
		test: {
			include: ['src/**/*.test.ts'],
			// Lock TZ so date formatting tests are deterministic across machines.
			env: { TZ: 'UTC' }
		},
		worker: {
			format: 'es'
		},
		plugins: [
			sveltekit(),
			tailwindcss(),
			paraglideVitePlugin({
				project: './project.inlang',
				outdir: './src/lib/paraglide',
				// Cookie before preferredLanguage so the settings menu can override the
				// browser-detected language. With the reverse order, setLocale() writes
				// the cookie but preferredLanguage still wins on every getLocale call.
				strategy: ['cookie', 'preferredLanguage', 'baseLocale'],
				emitTsDeclarations: true,
				// One module per locale so the client can load just the active one.
				outputStructure: 'locale-modules'
			}),
			paraglideLocaleSplit('en'),
			...(isRemoteLiveUrl ? [] : [serveDirectory('/live', localLiveDir)])
		],
		server: {
			allowedHosts: ['space.ilus.pw'],
			host: '0.0.0.0',
			proxy: {
				'/data': exportProxy(dataTarget, '/data'),
				// Only stood up for a remote images origin; otherwise /data covers it.
				...(isRemoteImagesUrl ? { '/images': exportProxy(configuredImagesUrl, '/images') } : {}),
				...(isRemoteLiveUrl ? { '/live': exportProxy(configuredLiveUrl, '/live') } : {})
			}
		}
	};
});

/** A dev proxy onto one export origin. Origin and Referer are stripped so the
 *  remote answers as it would a plain GET, with no CORS preflight in the way. */
function exportProxy(target: string, prefix: string): ProxyOptions {
	return {
		target,
		changeOrigin: true,
		rewrite: (path) => path.slice(prefix.length),
		configure: (proxy) => {
			proxy.on('proxyReq', (proxyReq) => {
				proxyReq.removeHeader('origin');
				proxyReq.removeHeader('referer');
			});
		}
	};
}

/** Files of one directory under a URL prefix, uncached: the live feed is
 *  rewritten in place, and a heuristic cache would hold yesterday's copy. */
function serveDirectory(prefix: string, dir: string): Plugin {
	const root = resolve(dir);
	return {
		name: 'space-map-serve-directory',
		configureServer(server) {
			server.middlewares.use(prefix, (req, res, next) => {
				const path = normalize(join(root, decodeURIComponent(req.url?.split('?')[0] ?? '/')));
				if (!path.startsWith(root + sep)) return next();
				let size: number;
				try {
					const stat = statSync(path);
					if (!stat.isFile()) return next();
					size = stat.size;
				} catch {
					return next();
				}
				res.setHeader('Content-Type', 'application/json');
				res.setHeader('Content-Length', size);
				res.setHeader('Cache-Control', 'no-store');
				createReadStream(path).pipe(res);
			});
		}
	};
}
