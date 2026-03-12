import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vite';

const dataTarget = process.env.DATA_SERVER_URL ?? 'http://localhost:8080';

export default defineConfig({
	plugins: [sveltekit(), tailwindcss()],
	server: {
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
