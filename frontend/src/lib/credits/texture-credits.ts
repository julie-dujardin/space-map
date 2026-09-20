/**
 * Per-body imagery credits for the pages that draw textured spheres outside
 * the scene — the collection lineups and /compare. Several surface maps
 * (Steve Albers, FarGetaNik, …) are non-commercial works whose attribution is
 * a licence condition, so whatever draws them has to name the author.
 *
 * Read off the aggregated `credits.json` that also feeds /credits, fetched
 * once per session and keyed by object id per layer.
 */
import { dataBase } from '$lib/fetch/data-base';

export interface TextureSource {
	/** Author/host shown as the credit label (e.g. "Steve Albers", "NASA"). */
	organisation: string;
	/** Landing page for that author's map set. */
	source: string;
	license?: string;
}

/** The sibling bundles a sphere outside the scene can be drawn from. */
export type CreditedLayer = 'textures' | 'displacement';

type LayerCredits = Record<CreditedLayer, Map<string, TextureSource>>;

let cache: Promise<LayerCredits> | null = null;

function load(fetchFn: typeof globalThis.fetch): Promise<LayerCredits> {
	cache ??= (async () => {
		const out: LayerCredits = { textures: new Map(), displacement: new Map() };
		try {
			const res = await fetchFn(`${dataBase()}/v1/credits.json`);
			if (!res.ok) return out;
			const data = await res.json();
			for (const sys of data.systems ?? []) {
				for (const layer of Object.keys(out) as CreditedLayer[]) {
					for (const t of sys[layer] ?? []) {
						out[layer].set(t.body_id, {
							organisation: t.organisation,
							source: t.source,
							license: t.license
						});
					}
				}
			}
		} catch {
			/* credits are a nice-to-have; the lineup still renders without them */
		}
		return out;
	})();
	return cache;
}

/** One layer's credits keyed by body id (`Object.id`). Empty on any failure —
 *  imagery credit is best-effort and must never block a lineup from rendering. */
export async function loadLayerCredits(
	layer: CreditedLayer,
	fetchFn: typeof globalThis.fetch = fetch
): Promise<Map<string, TextureSource>> {
	return (await load(fetchFn))[layer];
}

/** Surface-map credits keyed by body id. */
export function loadTextureCredits(
	fetchFn: typeof globalThis.fetch = fetch
): Promise<Map<string, TextureSource>> {
	return loadLayerCredits('textures', fetchFn);
}
