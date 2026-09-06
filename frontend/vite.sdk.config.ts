import { readdirSync, readFileSync, rmSync } from 'node:fs';
import { basename } from 'node:path';
import { fileURLToPath } from 'node:url';
import { Extractor, ExtractorConfig, ExtractorLogLevel } from '@microsoft/api-extractor';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import ts from 'typescript';
import { defineConfig, type Plugin } from 'vite';

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

const BANNER = '/*! spacemap SDK — https://spacemap.co — Mozilla Public License 2.0 */';

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

/** `index.d.ts` for the package: tsc declares the entry's reach into a scratch
 *  tree, api-extractor rolls it into one file. Both see only that reach plus
 *  the globals SvelteKit would add (runes, `?worker` modules), so the app's
 *  files add neither diagnostics nor ambient modules. */
function bundledTypes(outDir: string): Plugin {
	const tsconfigPath = here('./tsconfig.json');
	const scratch = `${outDir}/types`;
	const entry = `${scratch}/sdk/index.d.ts`;
	// The project's own globals: Intl.DurationFormat, which TypeScript's lib lacks.
	const ambient = here('./src/lib/types/intl-duration.d.ts');
	const shared = { types: ['svelte', 'vite/client'] };
	return {
		name: 'sdk-bundled-types',
		closeBundle() {
			const tsconfig = ts.readConfigFile(tsconfigPath, ts.sys.readFile).config;
			const parsed = ts.parseJsonConfigFileContent(
				{ ...tsconfig, files: ['src/sdk/index.ts', ambient], include: [] },
				ts.sys,
				here('.'),
				undefined,
				tsconfigPath
			);
			const program = ts.createProgram(parsed.fileNames, {
				...parsed.options,
				...shared,
				declaration: true,
				emitDeclarationOnly: true,
				noEmit: false,
				rootDir: here('./src'),
				outDir: scratch
			});
			const diagnostics = [...ts.getPreEmitDiagnostics(program), ...program.emit().diagnostics];
			if (diagnostics.length)
				this.error(
					ts.formatDiagnosticsWithColorAndContext(diagnostics, {
						getCanonicalFileName: (name) => name,
						getCurrentDirectory: ts.sys.getCurrentDirectory,
						getNewLine: () => '\n'
					})
				);
			const result = Extractor.invoke(
				ExtractorConfig.prepare({
					configObject: {
						projectFolder: here('.'),
						mainEntryPointFilePath: entry,
						// satellite.js is inside the bundle, so its types go inside too.
						bundledPackages: ['satellite.js'],
						newlineKind: 'lf',
						compiler: {
							overrideTsconfig: {
								compilerOptions: {
									...shared,
									target: 'esnext',
									module: 'esnext',
									moduleResolution: 'bundler',
									lib: ['esnext', 'DOM', 'DOM.Iterable'],
									strict: true,
									skipLibCheck: true,
									paths: { '$lib/*': [`${scratch}/lib/*`] }
								},
								files: [entry, ambient],
								include: []
							}
						},
						dtsRollup: { enabled: true, publicTrimmedFilePath: `${outDir}/index.d.ts` },
						apiReport: { enabled: false },
						docModel: { enabled: false },
						tsdocMetadata: { enabled: false },
						messages: {
							// Every type the surface reaches is a "forgotten export" to it.
							extractorMessageReporting: {
								'ae-forgotten-export': { logLevel: ExtractorLogLevel.None },
								'ae-missing-release-tag': { logLevel: ExtractorLogLevel.None },
								'ae-unresolved-link': { logLevel: ExtractorLogLevel.None }
							},
							tsdocMessageReporting: { default: { logLevel: ExtractorLogLevel.None } }
						}
					},
					configObjectFullPath: undefined,
					packageJsonFullPath: here('./package.json')
				}),
				{ localBuild: true }
			);
			rmSync(scratch, { recursive: true });
			if (!result.succeeded) this.error(`api-extractor reported ${result.errorCount} errors`);
		}
	};
}

/** Files that ship next to the bundle as they are. */
function copied(files: string[]): Plugin {
	return {
		name: 'sdk-copied-files',
		generateBundle() {
			for (const file of files)
				this.emitFile({ type: 'asset', fileName: basename(file), source: readFileSync(file) });
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
			npm
				? [
						bundledTypes(here('./dist/sdk-npm')),
						copied(readdirSync(here('./src/sdk/npm')).map((file) => here(`./src/sdk/npm/${file}`)))
					]
				: // The demo ships next to the CDN bundle, so `vite preview` serves both
					// from an origin that is neither the app's nor the data's.
					copied([here('./src/sdk/demo.html')])
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
			sourcemap: true,
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
