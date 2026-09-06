import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { defineConfig, type Plugin } from 'vite';

// The embeddable SDK: `src/sdk/index.ts` and the core under it, built as one
// script with no SvelteKit in it. The app's vite.config.ts is untouched.

const here = (path: string) => fileURLToPath(new URL(path, import.meta.url));

/** Workers ride inside the script: one file that works from any origin, with
 *  no path back to where it was loaded from. */
function inlineWorkers(): Plugin {
	return {
		name: 'sdk-inline-workers',
		enforce: 'pre',
		resolveId(source, importer, options) {
			if (!source.endsWith('?worker')) return null;
			return this.resolve(`${source}&inline`, importer, { ...options, skipSelf: true });
		}
	};
}

const BANNER = '/*! spacemap SDK — https://spacemap.co — Mozilla Public License 2.0 */';

/** One script is the whole SDK: lib mode writes CSS to its own file, so fold
 *  it into the entry, and fail if the entry needs any other file at runtime.
 *  The banner goes in here too: the minifier strips it off `output.banner`. */
function singleFile(): Plugin {
	// Emitted with the first output format only; later formats reuse it.
	let css = '';
	return {
		name: 'sdk-single-file',
		enforce: 'post',
		generateBundle(_options, bundle) {
			for (const [name, item] of Object.entries(bundle)) {
				if (item.type !== 'asset' || !name.endsWith('.css')) continue;
				css += item.source;
				delete bundle[name];
			}
			const entry = Object.values(bundle).find((item) => item.type === 'chunk' && item.isEntry);
			if (entry?.type !== 'chunk') return;
			const needs = [...entry.imports, ...entry.dynamicImports];
			if (needs.length)
				this.error(`the SDK entry must stand alone, but imports ${needs.join(', ')}`);
			// What remains under assets/ is a sub-build's sourcemap for code that got inlined.
			for (const name of Object.keys(bundle)) if (name.startsWith('assets/')) delete bundle[name];
			entry.code += `\n(function(){var s=document.createElement('style');s.textContent=${JSON.stringify(css)};document.head.appendChild(s);})();\n`;
			entry.code = `${BANNER}\n${entry.code}`;
			// One more line above the code: the sourcemap gets an empty line to match.
			const map = bundle[`${entry.fileName}.map`];
			if (map?.type === 'asset') {
				const json = JSON.parse(String(map.source));
				json.mappings = `;${json.mappings}`;
				map.source = JSON.stringify(json);
			}
		}
	};
}

/** The demo ships next to the bundle, so `vite preview` serves both from an
 *  origin that is neither the app's nor the data's. */
function emitDemo(): Plugin {
	return {
		name: 'sdk-demo',
		generateBundle() {
			this.emitFile({
				type: 'asset',
				fileName: 'demo.html',
				source: readFileSync(here('./src/sdk/demo.html'), 'utf8')
			});
		}
	};
}

export default defineConfig({
	plugins: [svelte({ configFile: false }), inlineWorkers(), singleFile(), emitDemo()],
	resolve: {
		alias: {
			$lib: here('./src/lib'),
			'#wasm-single-thread': here('./src/sdk/no-wasm.ts'),
			'#wasm-multi-thread': here('./src/sdk/no-wasm.ts')
		}
	},
	worker: { format: 'es' },
	build: {
		outDir: 'dist/sdk',
		sourcemap: true,
		lib: {
			entry: here('./src/sdk/index.ts'),
			name: 'spacemap',
			formats: ['es', 'iife'],
			fileName: (format) => (format === 'es' ? 'spacemap.js' : 'spacemap.iife.js')
		},
		rollupOptions: {
			output: {
				// Served from a CDN, not fed to a bundler: strip whitespace from the ES
				// build too, which lib mode otherwise keeps for tree-shaking annotations.
				minify: true
			}
		}
	},
	preview: { host: '0.0.0.0' }
});
