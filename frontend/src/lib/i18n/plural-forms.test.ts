import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import { locales } from '$lib/paraglide/runtime';

type Variant = { declarations?: string[]; selectors: string[]; match: Record<string, string> };

const messagesDir = new URL('../../../messages/', import.meta.url);

/** Categories that engines before CLDR 42 still select (Hebrew "many" for 20, 30, …). */
const legacyCategories: Partial<Record<string, string[]>> = { he: ['many'] };

// Paraglide returns the message key when no branch matches the plural category.
describe('plural messages cover every CLDR category of their locale', () => {
	for (const locale of locales) {
		it(locale, () => {
			const messages = JSON.parse(fs.readFileSync(new URL(`${locale}.json`, messagesDir), 'utf8'));
			const categories = [
				...new Intl.PluralRules(locale).resolvedOptions().pluralCategories,
				...(legacyCategories[locale] ?? [])
			];
			const gaps: string[] = [];
			for (const [key, value] of Object.entries(messages)) {
				if (!Array.isArray(value)) continue;
				for (const variant of value as Variant[]) {
					for (const declaration of variant.declarations ?? []) {
						const selector = declaration.match(/^local (\w+) = \w+: plural\b/)?.[1];
						if (!selector) continue;
						const index = variant.selectors.indexOf(selector);
						const present = new Set(
							Object.keys(variant.match).map((m) => m.split(/,\s*/)[index].split('=')[1])
						);
						if (present.has('*')) continue;
						const missing = categories.filter((c) => !present.has(c));
						if (missing.length) gaps.push(`${key}: ${missing.join(', ')}`);
					}
				}
			}
			expect(gaps).toEqual([]);
		});
	}
});
