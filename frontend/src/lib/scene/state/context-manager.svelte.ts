import type { PositionedBody } from '$lib/types/objects';
import { CreditsStore } from '$lib/scene/state/credits.svelte';
import { BodyIndex } from '$lib/scene/state/bodies.svelte';
import { VisibilityController } from '$lib/scene/visibility/controller.svelte';
import type { ChebyshevStore } from '$lib/fetch/position/chebyshev/store';
import type { ProbeStore } from '$lib/fetch/position/probes/store';
import type { ZoneRefresher } from '$lib/scene/zone-refresher';
import { loadScene } from '$lib/scene/setup/scene-load';

/**
 * Top-level state holder for the rendered scene. Composes four sub-stores —
 * bodies, credits, visibility, plus the loading/error reactive pair — and
 * holds the loader-lifetime handles (chebStore, probeStore, refresher) that
 * {@link loadScene} populates during `load()`.
 */
export class ContextManager {
	/** Body store: every loaded `PositionedBody`, parent/child graph, dirty
	 *  zone markers, and version counters for reactive consumers. */
	bodies = new BodyIndex();

	/** Attribution state: per-body imagery credits, skybox credit, orbit-source set. */
	credits = new CreditsStore();

	/** Focus state + per-frame visibility decisions. Reads body topology from
	 *  {@link BodyIndex}; the rendering side in `visibility/update.ts` reads
	 *  VISIBILITY values from here and applies them to Three.js objects. */
	visibility = new VisibilityController(this.bodies, () => this.probeStore);

	loading = $state(true);
	error = $state<string | null>(null);

	/**
	 * Chebyshev polynomial ephemeris for SPICE-sourced major bodies. Null until
	 * the metadata.json fetch in {@link loadScene} resolves; stays null if the
	 * export ships no chebyshev block.
	 */
	chebStore: ChebyshevStore | null = null;
	/**
	 * Per-zone probe sub-chunks (Kepler-pure / Kepler-drift / Chebyshev). Null
	 * until metadata resolves; stays null when the export ships no probe
	 * zones. The renderer's per-frame update path consults it for any body
	 * whose `orbitalSource === SPICE_PROBE`.
	 */
	probeStore: ProbeStore | null = null;

	/** Hot-reload driver for time-segmented (Earth SGP4 sats) and chunk-indexed
	 *  (moons Method-C secular elements) zones. Set at the end of {@link loadScene}
	 *  once the loader and metadata are available. */
	refresher: ZoneRefresher | null = null;

	/** Look up any body by ID. Carve-out delegate — see {@link BodyIndex.getBody}. */
	getBody(id: string, zone?: string): PositionedBody | undefined {
		return this.bodies.getBody(id, zone);
	}

	async load(date: Date, targetId?: string): Promise<void> {
		try {
			await loadScene(this, date, targetId);
		} catch (e) {
			this.loading = false;
			throw e;
		}
	}

	/** Per-frame hook called by the renderer when sim jd advances. Drives
	 *  hot-reload of time-segmented zones (Earth SGP4 sats) and chunk-indexed
	 *  zones (moons Method-C-fit elements expire each chunk). */
	refreshTick(date: Date): void {
		this.refresher?.tick(date);
	}
}
