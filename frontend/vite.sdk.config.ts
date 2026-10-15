import { readdirSync, readFileSync } from 'node:fs';
import { gzipSync } from 'node:zlib';
import { basename } from 'node:path';
import { fileURLToPath } from 'node:url';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { defineConfig, type Plugin } from 'vite';
import { writeSdkTypes } from './sdk-types';
import { NOTICES, thirdPartyNotices } from './third-party-notices';

// The embeddable SDK: `src/sdk/index.ts` and the core under it, built as one
// script with no SvelteKit in it. The default build is the CDN's (ES + IIFE,
// every dependency inside); `--mode npm` builds the package (ES only, types
// next to it, three.js left to the host's copy). The app's vite.config.ts is
// untouched.

const here = (path: string) => fileURLToPath(new URL(path, import.meta.url));
const noWasm = here('./src/lib/math/orbit/no-wasm.ts');

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

const BANNER = `/*! spacemap SDK — https://spacemap.co — Mozilla Public License 2.0. Bundles MIT and ISC libraries: ${NOTICES} in the spacemap npm package. */`;

/** One script is the whole SDK: lib mode writes CSS to its own file, so fold
 *  it into the entry, and fail if the entry needs any other emitted file at
 *  runtime (externals are the host's to provide). The banner goes in here
 *  too: the minifier strips it off `output.banner`. */
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
			const needs = [...entry.imports, ...entry.dynamicImports].filter((name) => name in bundle);
			if (needs.length)
				this.error(`the SDK entry must stand alone, but imports ${needs.join(', ')}`);
			// What remains under assets/ is a sub-build's sourcemap for code that got inlined.
			for (const name of Object.keys(bundle)) if (name.startsWith('assets/')) delete bundle[name];
			// Without a DOM the styles have nowhere to go, and the package must still import on a server.
			entry.code += `\n(function(){if(typeof document==='undefined')return;var s=document.createElement('style');s.textContent=${JSON.stringify(css)};document.head.appendChild(s);})();\n`;
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

/** The package's `index.d.ts`, and the API report in `etc/`. */
function bundledTypes(outDir: string): Plugin {
	return { name: 'sdk-bundled-types', closeBundle: () => writeSdkTypes(outDir) };
}

/** What the CDN copy may weigh, gzipped, since that is what a page downloads.
 *  A budget rather than a target: the map carries a renderer and an ephemeris,
 *  and the number is here to catch a dependency landing in it by accident. */
const MAX_GZIP_BYTES = 500 * 1024;

function sizeBudget(outDir: string, file: string): Plugin {
	return {
		name: 'sdk-size-budget',
		closeBundle() {
			const bytes = gzipSync(readFileSync(`${outDir}/${file}`)).length;
			const kb = (n: number) => `${(n / 1024).toFixed(1)} kB`;
			if (bytes > MAX_GZIP_BYTES)
				this.error(`${file} is ${kb(bytes)} gzipped, over the ${kb(MAX_GZIP_BYTES)} budget`);
			this.info(`${file}: ${kb(bytes)} gzipped, of ${kb(MAX_GZIP_BYTES)}`);
		}
	};
}

/** Files that ship next to the bundle as they are, under `dir`. A `.template`
 *  infix is dropped on the way in: the package manifest is named that at rest
 *  so the source directory is not itself publishable. */
function copied(files: string[], dir = ''): Plugin {
	return {
		name: `sdk-copied-files${dir && `-${dir}`}`,
		generateBundle() {
			for (const file of files)
				this.emitFile({
					type: 'asset',
					fileName: `${dir}${basename(file).replace('.template', '')}`,
					source: readFileSync(file)
				});
		}
	};
}

export default defineConfig(({ mode }) => {
	const npm = mode === 'npm';
	return {
		plugins: [
			svelte({ configFile: false }),
			inlineWorkers(),
			singleFile(),
			npm ? [] : thirdPartyNotices(),
			npm
				? [
						bundledTypes(here('./dist/sdk-npm')),
						copied(readdirSync(here('./src/sdk/npm')).map((file) => here(`./src/sdk/npm/${file}`))),
						// The CDN copies ride in the package too: jsDelivr serves them from
						// there, so the package needs no CDN of its own. The CDN build runs
						// first (build:sdk:npm), and its sourcemaps stay out like the
						// package's own.
						copied([here('./dist/sdk/spacemap.js'), here('./dist/sdk/spacemap.iife.js')], 'dist/'),
						// The CDN build's notices cover the package's own bundle too: the
						// package externalizes three.js and carries nothing else extra.
						copied([here(`./dist/sdk/${NOTICES}`)])
					]
				: [
						// The demos ship next to the CDN bundle, so `vite preview` serves
						// them from an origin that is neither the app's nor the data's.
						// three.js goes with them, unbundled: the demo builds a mesh of
						// its own, and a page on the CDN copy has no way into the one
						// inside it. It is the demo's dependency, not the SDK's.
						copied([
							here('./src/sdk/index.html'),
							here('./src/sdk/all.html'),
							here('./src/sdk/demo.html'),
							here('./src/sdk/flatmap.html'),
							here('./src/sdk/panorama.html'),
							here('./src/sdk/systemmap.html'),
							here('./node_modules/three/build/three.module.min.js'),
							here('./node_modules/three/build/three.core.min.js')
						]),
						sizeBudget(here('./dist/sdk'), 'spacemap.iife.js')
					]
		],
		resolve: {
			alias: {
				$lib: here('./src/lib'),
				'#wasm-single-thread': noWasm,
				'#wasm-multi-thread': noWasm
			}
		},
		worker: { format: 'es' },
		build: {
			outDir: npm ? 'dist/sdk-npm' : 'dist/sdk',
			// The package would carry more sourcemap than code, and the source it
			// maps to is on GitHub; the CDN copy keeps one, having no other.
			sourcemap: !npm,
			lib: {
				entry: here('./src/sdk/index.ts'),
				name: 'spacemap',
				formats: npm ? ['es'] : ['es', 'iife'],
				fileName: (format) =>
					npm ? 'index.js' : format === 'es' ? 'spacemap.js' : 'spacemap.iife.js'
			},
			rollupOptions: {
				// The host's three.js, so a page that already renders with it does not
				// carry two copies.
				external: npm ? [/^three(\/|$)/] : undefined,
				output: {
					// The CDN copy is served as is, so strip the whitespace lib mode keeps
					// for tree-shaking annotations; the package leaves that to the host's
					// bundler.
					minify: !npm
				}
			}
		},
		preview: { host: '0.0.0.0' }
	};
});
