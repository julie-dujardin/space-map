/**
 * Surface-imagery credits for the collection-page lineups. The lineup hero
 * renders textured spheres (BodyLineup), so the bodies it shows must credit
 * their texture authors — several (Steve Albers, FarGetaNik, …) are
 * non-commercial maps whose attribution is a licence condition.
 *
 * The aggregated `credits.json` (also feeding the standalone /credits page)
 * carries one entry per textured body; we load it once and key it by object
 * id so a lineup can look up exactly the bodies on screen.
 */
import { DATA_BASE } from '$lib/fetch/data-base';

export interface TextureSource {
	/** Author/host shown as the credit label (e.g. "Steve Albers", "NASA"). */
	organisation: string;
	/** Landing page for that author's map set. */
	source: string;
}

let cache: Promise<Map<string, TextureSource>> | null = null;

/** Texture credits keyed by body id (`Object.id`), loaded once per session.
 *  Returns an empty map on any failure — imagery credit is best-effort and
 *  must never block the lineup from rendering. */
export function loadTextureCredits(
	fetchFn: typeof globalThis.fetch = fetch
): Promise<Map<string, TextureSource>> {
	if (cache) return cache;
	cache = (async () => {
		const out = new Map<string, TextureSource>();
		try {
			const res = await fetchFn(`${DATA_BASE}/v1/credits.json`);
			if (!res.ok) return out;
			const data = await res.json();
			for (const sys of data.systems ?? []) {
				for (const t of sys.textures ?? []) {
					out.set(t.body_id, { organisation: t.organisation, source: t.source });
				}
			}
		} catch {
			/* credits are a nice-to-have; the lineup still renders without them */
		}
		return out;
	})();
	return cache;
}
