/**
 * Fetch per-language element labels (array index → localized name).
 */

const SUPPORTED_LANGUAGES = ['en', 'fr', 'ja', 'zh', 'ar', 'ru'];

/** Return the best supported language based on browser preferences. */
export function preferredLanguage(): string {
	for (const pref of navigator.languages) {
		const base = pref.split('-')[0].toLowerCase();
		if (SUPPORTED_LANGUAGES.includes(base)) return base;
	}
	return 'en';
}

export async function fetchLabels(lang = preferredLanguage()): Promise<Map<number, string>> {
	const res = await fetch(`/data/v1/element_labels/${lang}.json`);
	if (!res.ok) throw new Error(`Failed to fetch labels for ${lang}: ${res.status}`);
	const data: Record<string, string> = await res.json();
	return new Map(Object.entries(data).map(([k, v]) => [Number(k), v]));
}
