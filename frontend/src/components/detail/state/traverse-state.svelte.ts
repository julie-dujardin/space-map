/** A probe's own surface panoramas: the traverse it drove, taken from the body
 *  it drove on. */

import { fetchPanoramaIndex } from '$lib/fetch/panoramas';
import { fetchObjectDetail, type PanoramaEntry } from '$lib/fetch/objects/object-data';
import { meanRadiusKm } from '$lib/fetch/objects/physical';
import { panoramaHighlights } from '$lib/panorama/highlights';

/** What the Surface tab shows of one probe: enough of the traverse to draw it,
 *  and the handful of panoramas that stand for it. */
export interface Traverse {
	bodyId: string;
	bodyName: string;
	/** Mean radius of the body, kilometres; sizes the minimap's scale bar. */
	radiusKm: number;
	/** The mission's panoramas in time order — the whole ground track. */
	entries: PanoramaEntry[];
	/** The ones the panel pictures. */
	highlights: PanoramaEntry[];
}

/** How many panoramas the tab pictures. Past this the strip stops being a
 *  selection and becomes the traverse, which the viewer's timeline already is. */
export const HIGHLIGHT_LIMIT = 20;

export interface TraverseStateDeps {
	/** The probe this page is, or null where the page is anything else. */
	probeId: () => string | undefined;
}

export class TraverseState {
	traverse = $state<Traverse | null>(null);
	/** True while this probe's traverse is still unknown, so the tab can hold
	 *  its place rather than appear once the index answers. */
	loading = $state(false);

	constructor(d: TraverseStateDeps) {
		$effect(() => {
			const probeId = d.probeId();
			this.traverse = null;
			if (!probeId) {
				this.loading = false;
				return;
			}
			this.loading = true;
			let stale = false;
			void load(probeId)
				.catch((err) => {
					console.warn(`[traverse] failed to load ${probeId}:`, err);
					return null;
				})
				.then((traverse) => {
					if (stale) return;
					this.traverse = traverse;
					this.loading = false;
				});
			return () => {
				stale = true;
			};
		});
	}
}

async function load(probeId: string): Promise<Traverse | null> {
	const index = await fetchPanoramaIndex();
	for (const body of index) {
		const mission = body.missions.find((m) => m.probe === probeId)?.mission;
		if (!mission) continue;
		const detail = await fetchObjectDetail(body.id);
		const global = detail.global;
		const entries = global?.panoramas?.filter((e) => e.mission === mission) ?? [];
		if (!entries.length) return null;
		return {
			bodyId: body.id,
			bodyName: detail.localized?.name ?? global?.name ?? body.id,
			radiusKm: (global && meanRadiusKm(global)) ?? 0,
			entries,
			highlights: panoramaHighlights(entries, HIGHLIGHT_LIMIT)
		};
	}
	return null;
}
