/// <reference types="vitest/config" />
import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { paraglideVitePlugin } from '@inlang/paraglide-js';
import { defineConfig, loadEnv, type Plugin } from 'vite';
import fs from 'node:fs';
import path from 'node:path';

// WIP cat-moons override: serve the few injected group files from
// static/dev-data/ before the /data proxy reaches prod. Delete this plugin (and
// the static/dev-data/ dir) once a real export ships cat-moons.
function devMoonsOverlay(): Plugin {
	const root = path.resolve('static/dev-data');
	const overrides = new Set([
		'/v1/groups/__index__.json',
		'/v1/groups/__global__/0.json.gz',
		'/v1/groups/en/0.json.gz',
		'/v1/groups/en/1.json.gz'
	]);
	return {
		name: 'dev-moons-overlay',
		configureServer(server) {
			server.middlewares.use((req, res, next) => {
				const url = req.url ?? '';
				if (!url.startsWith('/data/')) return next();
				const rel = url.replace(/^\/data/, '').split('?')[0];
				if (!overrides.has(rel)) return next();
				fs.readFile(path.join(root, rel), (err, buf) => {
					if (err) return next();
					// No Content-Encoding: the client gunzips .json.gz itself.
					res.setHeader(
						'Content-Type',
						rel.endsWith('.gz') ? 'application/gzip' : 'application/json'
					);
					res.end(buf);
				});
			});
		}
	};
}

// If PUBLIC_DATA_URL is an absolute URL (e.g. https://static.spacemap.co), route
// it through the dev proxy: the browser keeps hitting /data (same-origin, no
// preflight) while the proxy fetches from the remote without forwarding Origin.
const envFromFiles = loadEnv(process.env.NODE_ENV ?? 'development', process.cwd(), '');
const configuredDataUrl = process.env.PUBLIC_DATA_URL ?? envFromFiles.PUBLIC_DATA_URL ?? '/data';
const isRemoteDataUrl = /^https?:\/\//i.test(configuredDataUrl);
const dataTarget = isRemoteDataUrl
	? configuredDataUrl
	: (process.env.DATA_SERVER_URL ?? envFromFiles.DATA_SERVER_URL ?? 'http://localhost:8080');
if (isRemoteDataUrl) {
	process.env.PUBLIC_DATA_URL = '/data';
}

export default defineConfig({
	test: {
		include: ['src/**/*.test.ts'],
		// Lock TZ so date formatting tests are deterministic across machines.
		env: { TZ: 'UTC' }
	},
	worker: {
		format: 'es'
	},
	plugins: [
		devMoonsOverlay(),
		sveltekit(),
		tailwindcss(),
		paraglideVitePlugin({
			project: './project.inlang',
			outdir: './src/lib/paraglide',
			// Cookie before preferredLanguage so the settings menu can override the
			// browser-detected language. With the reverse order, setLocale() writes
			// the cookie but preferredLanguage still wins on every getLocale call.
			strategy: ['cookie', 'preferredLanguage', 'baseLocale'],
			emitTsDeclarations: true
		})
	],
	server: {
		allowedHosts: ['space.ilus.pw'],
		host: '0.0.0.0',
		proxy: {
			'/data': {
				target: dataTarget,
				changeOrigin: true,
				rewrite: (path) => path.replace(/^\/data/, ''),
				configure: (proxy) => {
					proxy.on('proxyReq', (proxyReq) => {
						proxyReq.removeHeader('origin');
						proxyReq.removeHeader('referer');
					});
				}
			}
		}
	}
});
