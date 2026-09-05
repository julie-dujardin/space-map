/// <reference types="vitest/config" />
import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { paraglideVitePlugin } from '@inlang/paraglide-js';
import { paraglideLocaleSplit } from './paraglide-locale-split';
import { defineConfig, loadEnv } from 'vite';

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
