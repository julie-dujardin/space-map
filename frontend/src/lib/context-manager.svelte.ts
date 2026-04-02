import { SvelteMap } from 'svelte/reactivity';
import { ObjectType, type PositionedBody } from '$lib/types/objects';
import { ChunkLoader } from '$lib/fetch/elements/chunk';

/** Three.js units: 1 AU = 10 units. At this distance, reveal the focused system. */
export const ZOOM_THRESHOLD = 10;

export class ContextManager {
	private readonly childrenByParent = new SvelteMap<number, PositionedBody[]>();
	private readonly bodiesById = new SvelteMap<number, PositionedBody>();

	// --- Reactive loading state ($state safe: only mutated during async load, never in useTask) ---
	loading = $state(true);
	error = $state<string | null>(null);
	majorBodies = $state<PositionedBody[]>([]);
	asteroidBodies = $state<PositionedBody[]>([]);
	spacecraftByParent = $state(new SvelteMap<number, PositionedBody[]>());

	// --- Visibility state (plain mutable: written from useTask every frame) ---
	focusedBodyId: number | null = null;
	isZoomedIn: boolean = false;
	activeSystemId: number | null = null;

	get allBodies(): PositionedBody[] {
		return [...this.bodiesById.values()];
	}

	async load(date: Date): Promise<void> {
		try {
			const loader = new ChunkLoader();
			const major: PositionedBody[] = [];
			major.push(...(await loader.process('sun', 0, 0, date)));
			major.push(...(await loader.process('sun', 1, 0, date)));

			const metaRes = await fetch('/data/v1/metadata.json');
			if (!metaRes.ok) throw new Error(`Failed to fetch metadata: ${metaRes.status}`);
			const metadata = await metaRes.json();

			const minorChunkArgs: { context: string; zoom: number; part: number }[] = [];
			for (const [context, ctxData] of Object.entries(metadata.contexts) as [
				string,
				{ zooms: Record<string, { parts: number }> }
			][]) {
				for (const [zoomStr, zoomData] of Object.entries(ctxData.zooms) as [
					string,
					{ parts: number }
				][]) {
					if (context !== 'sun' || Number(zoomStr) >= 2)
						for (let part = 0; part < Math.min(zoomData.parts, 20); part++)
							minorChunkArgs.push({ context, zoom: Number(zoomStr), part });
				}
			}
			const minors = (
				await Promise.all(
					minorChunkArgs.map(({ context, zoom, part }) => loader.process(context, zoom, part, date))
				)
			).flat();

			this.addBodies(major);
			this.addBodies(minors);

			// Split minors into asteroids vs spacecraft groups
			const asteroids: PositionedBody[] = [];
			const spacecraft = new SvelteMap<number, PositionedBody[]>();
			for (const b of minors) {
				if (b.data.objectType === ObjectType.SPACECRAFT) {
					const list = spacecraft.get(b.data.parentId) ?? [];
					list.push(b);
					spacecraft.set(b.data.parentId, list);
				} else {
					asteroids.push(b);
				}
			}

			this.majorBodies = major;
			this.asteroidBodies = asteroids;
			this.spacecraftByParent = spacecraft;
			this.loading = false;
		} catch (e) {
			this.error = e instanceof Error ? e.message : String(e);
			this.loading = false;
		}
	}

	addBodies(bodies: PositionedBody[]): void {
		for (const b of bodies) {
			this.bodiesById.set(b.data.id, b);
			const list = this.childrenByParent.get(b.data.parentId) ?? [];
			list.push(b);
			this.childrenByParent.set(b.data.parentId, list);
		}
	}

	/** Call from useTask every frame. Only updates when crossing the threshold. */
	updateCamera(dist: number): void {
		const zoomed = dist <= ZOOM_THRESHOLD;
		if (zoomed !== this.isZoomedIn) {
			this.isZoomedIn = zoomed;
			this.recomputeActiveSystem();
		}
	}

	setFocused(body: PositionedBody): void {
		if (body.data.id !== this.focusedBodyId) {
			this.focusedBodyId = body.data.id;
			this.recomputeActiveSystem();
		}
	}

	private recomputeActiveSystem(): void {
		if (!this.isZoomedIn || this.focusedBodyId === null) {
			this.activeSystemId = null;
			return;
		}
		const body = this.bodiesById.get(this.focusedBodyId);
		this.activeSystemId =
			!body || body.data.objectType === ObjectType.STAR ? null : body.data.parentId;
	}

	/** Moons are hidden until zoomed into their system. All other major bodies always visible. */
	isMajorBodyVisible(body: PositionedBody): boolean {
		if (body.data.objectType !== ObjectType.MOON) return true;
		return this.isInActiveSystem(body.data.parentId);
	}

	/** Full rendering = halo + trail. Suppressed for out-of-system bodies when zoomed in. */
	hasFullRendering(body: PositionedBody): boolean {
		const sysId = this.activeSystemId;
		if (!sysId) return true;
		return this.isInActiveSystem(body.data.parentId);
	}

	/**
	 * Whether a spacecraft point-cloud group should be shown.
	 * Sun-level groups (parentId=0 or parent is STAR) are always visible.
	 * Planet-orbiting groups are only visible when in the active system.
	 */
	isSpacecraftGroupVisible(groupParentId: number): boolean {
		if (groupParentId === 0) return true;
		const parent = this.bodiesById.get(groupParentId);
		if (parent?.data.objectType === ObjectType.STAR) return true;
		const sysId = this.activeSystemId;
		if (!sysId) return false;
		if (groupParentId === sysId) return true;
		return (this.childrenByParent.get(sysId) ?? []).some((c) => c.data.id === groupParentId);
	}

	/**
	 * True if the given parentId belongs to the active system.
	 * Handles two levels: parentId === barycenter, or parentId is a direct child of the barycenter.
	 */
	private isInActiveSystem(parentId: number): boolean {
		const sysId = this.activeSystemId;
		if (!sysId) return false;
		if (parentId === sysId) return true;
		return (this.childrenByParent.get(sysId) ?? []).some((c) => c.data.id === parentId);
	}
}
