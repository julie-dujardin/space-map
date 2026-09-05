import { baseLocale, type Locale } from '$lib/paraglide/runtime';

type MessageModule = Record<string, (inputs?: object) => string>;

/** Locale modules the client has fetched. The message index reads these in
 *  place of its static imports (see `paraglide-locale-split.ts`), so a page
 *  ships the base locale only. */
export const loadedLocaleMessages: Partial<Record<Locale, MessageModule>> = {};

const loaders = import.meta.glob<MessageModule>(['$lib/paraglide/messages/*.js', '!**/_index.js']);

/** Fetch one locale's messages; must land before anything renders in it. */
export async function loadLocaleMessages(locale: Locale): Promise<void> {
	if (locale === baseLocale || loadedLocaleMessages[locale]) return;
	const key = Object.keys(loaders).find((k) => k.endsWith(`/${locale}.js`));
	if (!key) return;
	loadedLocaleMessages[locale] = await loaders[key]();
}
