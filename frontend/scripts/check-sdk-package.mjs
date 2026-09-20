// Checks the built npm package before it is published: the tarball is assembled
// by the build, so nothing else ever looks at it.
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

const dist = new URL('../dist/sdk-npm/', import.meta.url);
const at = (file) => new URL(file, dist);
const failures = [];
const check = (condition, message) => void (condition || failures.push(message));

check(existsSync(dist), 'dist/sdk-npm is missing — run pnpm build:sdk:npm');
if (failures.length) {
	console.error(failures[0]);
	process.exit(1);
}

const manifest = JSON.parse(readFileSync(at('package.json'), 'utf8'));
for (const [field, file] of [
	['exports types', manifest.exports?.['.']?.types],
	['exports default', manifest.exports?.['.']?.default],
	['main', manifest.main]
]) {
	if (!file) continue;
	check(existsSync(at(file)), `${field} points at ${file}, which is not in the package`);
}
check(manifest.license === 'MPL-2.0', `license is ${manifest.license}, expected MPL-2.0`);
check(existsSync(at('LICENSE')), 'no LICENSE in the package — MPL-2.0 requires the notice');
check(existsSync(at('README.md')), 'no README.md in the package');
// The README quotes a CDN URL; one from a previous version would be the one people copy.
check(
	readFileSync(at('README.md'), 'utf8').includes(`cdn.spacemap.co/${manifest.version}/`),
	`README.md does not point at cdn.spacemap.co/${manifest.version}/`
);

// Whatever sits here is published, so build leftovers are a packaging bug.
const expected = new Set(['index.js', 'index.d.ts', 'package.json', 'README.md', 'LICENSE']);
for (const entry of readdirSync(dist)) {
	const kind = statSync(at(entry)).isDirectory() ? 'directory' : 'file';
	check(expected.has(entry), `unexpected ${kind} in the publish root: ${entry}`);
}

// three.js is the host's; anything else bare would be an unlisted dependency.
const types = readFileSync(at('index.d.ts'), 'utf8');
for (const [, specifier] of types.matchAll(/from '([^'.][^']*)'/g))
	check(
		specifier === 'three',
		`index.d.ts imports ${specifier}, which the package does not depend on`
	);

// The package must import where there is no DOM: SSR frameworks load it on the server.
const sdk = await import(pathToFileURL(at('index.js').pathname));
for (const name of ['createMap', 'createFlatMap', 'createPanorama'])
	check(typeof sdk[name] === 'function', `${name} is not exported`);

for (const failure of failures) console.error(`✗ ${failure}`);
if (failures.length) process.exit(1);
console.log(`✓ ${manifest.name}@${manifest.version} is ready to publish`);
