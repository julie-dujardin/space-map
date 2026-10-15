import { mkdirSync, mkdtempSync, readFileSync, renameSync, rmSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { Extractor, ExtractorConfig, ExtractorLogLevel } from '@microsoft/api-extractor';
import { format, resolveConfig } from 'prettier';
import ts from 'typescript';

// The SDK's types: `index.d.ts` for the package, and the API report
// `etc/spacemap.api.md`. The npm build calls `writeSdkTypes`. `pnpm api-report`
// writes the report alone, for the pre-commit hook.

const here = (path: string) => fileURLToPath(new URL(path, import.meta.url));
const reportFolder = here('./etc');
const report = `${reportFolder}/spacemap.api.md`;

const MESSAGES = {
	// api-extractor calls each internal type that the API uses a "forgotten export".
	extractorMessageReporting: {
		'ae-forgotten-export': { logLevel: ExtractorLogLevel.None },
		'ae-missing-release-tag': { logLevel: ExtractorLogLevel.None },
		'ae-unresolved-link': { logLevel: ExtractorLogLevel.None }
	},
	tsdocMessageReporting: { default: { logLevel: ExtractorLogLevel.None } }
};

/** Writes `index.d.ts` into `outDir`, and writes the API report. tsc declares
 *  the files that the entry imports, and api-extractor rolls them into one
 *  file. Both read only these files and the globals that SvelteKit adds (runes,
 *  `?worker` modules). The other files of the app add no diagnostics and no
 *  ambient modules. */
export async function writeSdkTypes(outDir: string): Promise<void> {
	const tsconfigPath = here('./tsconfig.json');
	const scratch = `${outDir}/types`;
	const entry = `${scratch}/sdk/index.d.ts`;
	// The project's own global, Intl.DurationFormat. TypeScript's lib does not have it.
	const ambient = here('./src/lib/types/intl-duration.d.ts');
	const shared = { types: ['svelte', 'vite/client'] };
	const compilerOptions = {
		...shared,
		target: 'esnext',
		module: 'esnext',
		moduleResolution: 'bundler',
		lib: ['esnext', 'DOM', 'DOM.Iterable'],
		strict: true,
		skipLibCheck: true
	};
	mkdirSync(reportFolder, { recursive: true });
	try {
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
			throw new Error(
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
							compilerOptions: { ...compilerOptions, paths: { '$lib/*': [`${scratch}/lib/*`] } },
							files: [entry, ambient],
							include: []
						}
					},
					dtsRollup: { enabled: true, publicTrimmedFilePath: `${outDir}/index.d.ts` },
					// Written, and not compared. A review reads the committed report, so
					// a change to the API shows as a diff.
					apiReport: {
						enabled: true,
						reportFolder,
						reportFileName: 'spacemap.api.md',
						reportTempFolder: `${scratch}/api-report-temp`
					},
					docModel: { enabled: false },
					tsdocMetadata: { enabled: false },
					messages: MESSAGES
				},
				configObjectFullPath: undefined,
				packageJsonFullPath: here('./package.json')
			}),
			{ localBuild: true }
		);
		if (!result.succeeded) throw new Error(`api-extractor reported ${result.errorCount} errors`);
		// The committed report is in prettier's format. The same format here makes
		// a diff only when the API changes.
		const options = await resolveConfig(report);
		writeFileSync(
			report,
			await format(readFileSync(report, 'utf8'), { ...options, filepath: report })
		);
		// The trimmed rollup still declares internal types that nothing in it uses.
		// A second rollup of the trimmed file removes them.
		const trimmed = `${scratch}/trimmed.d.ts`;
		renameSync(`${outDir}/index.d.ts`, trimmed);
		const pruned = Extractor.invoke(
			ExtractorConfig.prepare({
				configObject: {
					projectFolder: here('.'),
					mainEntryPointFilePath: trimmed,
					newlineKind: 'lf',
					compiler: {
						overrideTsconfig: { compilerOptions, files: [trimmed, ambient], include: [] }
					},
					dtsRollup: { enabled: true, untrimmedFilePath: `${outDir}/index.d.ts` },
					apiReport: { enabled: false },
					docModel: { enabled: false },
					tsdocMetadata: { enabled: false },
					messages: MESSAGES
				},
				configObjectFullPath: undefined,
				packageJsonFullPath: here('./package.json')
			}),
			{ localBuild: true }
		);
		if (!pruned.succeeded) throw new Error(`api-extractor reported ${pruned.errorCount} errors`);
	} finally {
		rmSync(scratch, { recursive: true, force: true });
	}
}

if (import.meta.main) {
	// The declarations resolve their imports from their folder, so it is in the
	// project, as in the build. It is not in node_modules: there, api-extractor
	// treats a file as part of a package.
	mkdirSync(here('./dist'), { recursive: true });
	const outDir = mkdtempSync(here('./dist/types-'));
	try {
		await writeSdkTypes(outDir);
	} finally {
		rmSync(outDir, { recursive: true });
	}
}
