/// <reference types="vitest/config" />
import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { paraglideVitePlugin } from '@inlang/paraglide-js';
import { paraglideLocaleSplit } from './paraglide-locale-split';
import { defineConfig, type ProxyOptions } from 'vite';
import { fileURLToPath } from 'node:url';
import { readFileSync } from 'node:fs';
import { parseEnv } from 'node:util';

// Vite's own loadEnv lets process.env shadow the .env files, and the rewrites
// below put `/data` back into process.env; on an in-process restart (.env or
// this file changing) that rewrite would read as the configured origin and the
// proxy would silently fall back to the local export. Parse the files off disk
// instead, and ignore process.env once a rewrite has happened.
const mode = process.env.NODE_ENV ?? 'development';
const fileEnv: Record<string, string> = {};
for (const file of ['.env', '.env.local', `.env.${mode}`, `.env.${mode}.local`]) {
	try {
		Object.assign(fileEnv, parseEnv(readFileSync(file, 'utf8')));
	} catch {
		// No such .env file.
	}
}
const rewritten = process.env.SM_DEV_PROXY_REWROTE_ENV === '1';
const envVar = (key: string) => (rewritten ? undefined : process.env[key]) ?? fileEnv[key];

// An absolute PUBLIC_DATA_URL (e.g. https://static.spacemap.co) goes through the
// dev proxy: the browser keeps hitting /data (same-origin, no preflight) while
// the proxy fetches from the remote without forwarding Origin.
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

if (isRemoteDataUrl) process.env.PUBLIC_DATA_URL = '/data';
if (isRemoteImagesUrl) process.env.PUBLIC_IMAGES_URL = '/images';
if (isRemoteDataUrl || isRemoteImagesUrl) process.env.SM_DEV_PROXY_REWROTE_ENV = '1';

// satellite.js's optional WASM runtime: nothing calls it, and bundled it is a
// 310 kB chunk with a top-level await.
const noWasm = fileURLToPath(new URL('./src/lib/math/orbit/no-wasm.ts', import.meta.url));

export default defineConfig({
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
		paraglideLocaleSplit('en')
	],
	server: {
		allowedHosts: ['space.ilus.pw'],
		host: '0.0.0.0',
		proxy: {
			'/data': exportProxy(dataTarget, '/data'),
			// Only stood up for a remote images origin; otherwise /data covers it.
			...(isRemoteImagesUrl ? { '/images': exportProxy(configuredImagesUrl, '/images') } : {})
		}
	}
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
