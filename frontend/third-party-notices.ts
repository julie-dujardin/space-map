import { readdirSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import type { Plugin } from 'vite';

export const NOTICES = 'THIRD_PARTY_NOTICES.txt';

const PACKAGE_ROOT = /^\0?(.*\/node_modules\/(?:@[^/]+\/)?[^/@][^/]*)\//;
const STYLE_IMPORT = /^@import\s+['"]([^'"./][^'"]*)['"]/gm;

/** Packages a stylesheet imports by name. The CSS toolchain inlines them, so
 *  they never reach a chunk's module list. */
function stylesheetPackages(stylesheet: string): string[] {
	const names = [...readFileSync(stylesheet, 'utf8').matchAll(STYLE_IMPORT)].map((m) => m[1]);
	return names.map((name) => fileURLToPath(new URL(`./node_modules/${name}`, import.meta.url)));
}

/** The licences of what a build carries, one file next to it: MIT and ISC
 *  require their notice to travel with copies, and the minifier strips every
 *  comment. Packages are read off the chunks' module lists and the
 *  stylesheets' imports, so a dependency landing in the build brings its
 *  notice along unasked. */
export function thirdPartyNotices(stylesheets: string[] = []): Plugin {
	let server = false;
	return {
		name: 'third-party-notices',
		configResolved(config) {
			server = Boolean(config.build.ssr);
		},
		generateBundle(_options, bundle) {
			// The server build ships nothing to a reader, and a second output
			// format carries the same packages as the first.
			if (server || bundle[NOTICES]) return;
			const roots = new Set(stylesheets.flatMap(stylesheetPackages));
			for (const item of Object.values(bundle)) {
				if (item.type !== 'chunk') continue;
				for (const id of Object.keys(item.modules)) {
					const root = PACKAGE_ROOT.exec(id)?.[1];
					if (root) roots.add(root);
				}
			}
			const notices = [...roots]
				.map((root) => {
					const manifest = JSON.parse(readFileSync(`${root}/package.json`, 'utf8'));
					const license = readdirSync(root).find((file) => /^licen[cs]e/i.test(file));
					if (!license) this.error(`${manifest.name} ships no licence file to copy`);
					return {
						name: manifest.name as string,
						version: manifest.version as string,
						// Some manifests name no licence and ship only the file.
						license: manifest.license ? ` — ${manifest.license}` : '',
						text: readFileSync(`${root}/${license}`, 'utf8').trim()
					};
				})
				.sort(
					(a, b) =>
						a.name.localeCompare(b.name) ||
						a.version.localeCompare(b.version, undefined, { numeric: true })
				);
			const source = [
				'This bundle carries the following packages, under their own licences.',
				...notices.map(
					(n) =>
						`\n${'='.repeat(72)}\n${n.name} ${n.version}${n.license}\n${'='.repeat(72)}\n\n${n.text}`
				)
			].join('\n');
			this.emitFile({ type: 'asset', fileName: NOTICES, source: `${source}\n` });
		}
	};
}
