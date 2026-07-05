import adapter from '@sveltejs/adapter-cloudflare';

const dev = process.env.NODE_ENV !== 'production';

// connect-src: prod data/images/search are all HTTPS, so `https:` covers them
// without baking hostnames in. Dev adds local Meili + Vite's HMR websocket.
const connectSrc = ['self', 'https:'];
if (dev) connectSrc.push('http://127.0.0.1:7700', 'http://localhost:7700', 'ws:', 'wss:');

/** @type {import('@sveltejs/kit').Config} */
const config = {
	kit: {
		adapter: adapter(),
		// SPA (ssr=false): CSP ships as a <meta> to blunt injected-HTML scripts.
		// frame-ancestors can't live in a meta CSP, so SvelteKit emits it as an
		// HTTP header instead; the other security headers ride hooks.server.ts.
		csp: {
			mode: 'hash',
			directives: {
				'default-src': ['self'],
				'frame-ancestors': ['none'],
				// SvelteKit hashes its own inline script but not app.html's two, so
				// pin those. Hashes are stable (scripts read env from a meta, not
				// their body) — re-hash if edited. wasm-unsafe-eval covers Three.js.
				'script-src': [
					'self',
					'wasm-unsafe-eval',
					'sha256-DwoCeDQtDeE13/r23DyUnVrrkg6qiRPBM4fPbBJGXg0=',
					'sha256-NyWrMtyLz818JzVWmydOkQl+/Jy5D7WRRf0miIItV34='
				],
				// Svelte + Tailwind emit inline <style>; not a script vector.
				'style-src': ['self', 'unsafe-inline'],
				'img-src': ['self', 'data:', 'blob:', 'https:'],
				'font-src': ['self', 'data:'],
				'connect-src': connectSrc,
				'worker-src': ['self', 'blob:'],
				'object-src': ['none'],
				'base-uri': ['self']
			}
		}
	}
};

export default config;
