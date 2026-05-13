/// <reference types="vitest/config" />
import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { paraglideVitePlugin } from '@inlang/paraglide-js';
import { defineConfig } from 'vite';

const dataTarget = process.env.DATA_SERVER_URL ?? 'http://localhost:8080';

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
				rewrite: (path) => path.replace(/^\/data/, '')
			}
		}
	}
});
