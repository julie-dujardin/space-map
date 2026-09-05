import type { Plugin } from 'vite';

const INDEX_SUFFIX = '/paraglide/messages/_index.js';

/**
 * Client-only rewrite of paraglide's `locale-modules` index so a page ships
 * one locale instead of twelve. The generated dispatchers import every
 * locale module statically; this drops the non-base imports and routes those
 * branches through the registry that `$lib/i18n/locale-messages` fills with a
 * dynamic import before hydration. The server build keeps the static imports.
 */
export function paraglideLocaleSplit(baseLocale: string): Plugin {
	return {
		name: 'paraglide-locale-split',
		transform(code, id, options) {
			if (options?.ssr || !id.endsWith(INDEX_SUFFIX)) return null;
			return { code: splitIndex(code, baseLocale), map: null };
		}
	};
}

const IMPORT_RE = /^import \* as __(\w+) from "\.\/\w+\.js"\n/gm;
const DISPATCHER_RE =
	/^(export )?const (\w+) = \/\*\* @type \{[^\n]*\*\/ \(\(inputs(?: = \{\})?, options = \{\}\) => \{\n\tconst locale = experimentalStaticLocale \?\? options\.locale \?\? getLocale\(\)\n(?:\tif \(locale === "\w+"\) return __\w+\.\2\(inputs\)\n)+\treturn __\w+\.\2\(inputs\)\n\}\);$/gm;

export function splitIndex(code: string, baseLocale: string): string {
	const base = `__${baseLocale}`;
	let out = code.replace(IMPORT_RE, (line, locale: string) => (locale === baseLocale ? line : ''));
	let dispatchers = 0;
	// One factory call per message instead of a twelve-branch function each:
	// the locale modules export every message under its identifier.
	out = out.replace(DISPATCHER_RE, (_, exp: string | undefined, name: string) => {
		dispatchers++;
		return `${exp ?? ''}const ${name} = __msg("${name}")`;
	});
	const leftover = out.match(/\b__\w+\./g)?.filter((m) => m !== `${base}.`);
	if (dispatchers === 0 || (leftover && leftover.length > 0)) {
		throw new Error(
			`paraglide-locale-split: unexpected index shape (${dispatchers} dispatchers, leftover ${leftover?.slice(0, 3).join(' ')})`
		);
	}
	return (
		`import { loadedLocaleMessages as __lm } from "$lib/i18n/locale-messages"\n` +
		`const __msg = (name) => (inputs = {}, options = {}) => {\n` +
		`\tconst locale = experimentalStaticLocale ?? options.locale ?? getLocale()\n` +
		`\tif (locale !== "${baseLocale}") { const other = __lm[locale]?.[name]; if (other) return other(inputs) }\n` +
		`\treturn ${base}[name](inputs)\n` +
		`}\n` +
		out
	);
}
