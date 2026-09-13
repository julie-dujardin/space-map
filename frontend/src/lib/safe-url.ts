/**
 * Return `url` only when it resolves to an http(s) link, else undefined —
 * blocks `javascript:`/`data:` and other script-capable schemes from reaching
 * an `href`. Use for URLs sourced from external data (Commons/Wikidata image
 * metadata, source links) before binding them to an anchor.
 */
export function safeHttpUrl(url: string | null | undefined): string | undefined {
	if (!url) return undefined;
	try {
		const base = typeof window !== 'undefined' ? window.location.href : 'https://spacemap.co';
		const { protocol } = new URL(url, base);
		return protocol === 'http:' || protocol === 'https:' ? url : undefined;
	} catch {
		return undefined;
	}
}
