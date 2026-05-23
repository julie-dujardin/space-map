import type { Scene, TextureLoader, WebGLRenderer } from 'three';
import { ObjectType } from '$lib/types/objects';
import type { BodyObjects } from '$lib/scene/types';
import type { ContextManager } from '$lib/scene/context-manager.svelte';
import type { SimClock } from '$lib/scene/clock.svelte';
import { loadSystemData, unloadSystemTextures } from '$lib/scene/objects/construction';

/**
 * Owns the "which system's textures + orientation are currently resident"
 * decision. Tracks the currently loaded barycenter and a deferred-unload queue:
 * the previous system's textures stay resident until the in-flight focus
 * animation settles, so a fly that gets reversed mid-way doesn't thrash the
 * GPU. The caller drives draining via {@link drainPendingUnloads} when its
 * focus animation has finished.
 */
export class SystemDataLoader {
	private lastBaryId: string | null = null;
	private readonly pendingUnloads = new Set<string>();

	constructor(
		private readonly scene: Scene,
		private readonly ctx: ContextManager,
		private readonly renderer: WebGLRenderer,
		private readonly textureLoader: TextureLoader,
		private readonly bodyObjects: Map<string, BodyObjects>,
		private readonly clock: SimClock,
		private readonly onLoaded: () => void
	) {}

	/**
	 * Sync resident textures to the focused system. If the focus changed
	 * barycenters, queues the prior system for deferred unload and kicks off
	 * the new one's `loadSystemData` (textures + orientation + rings + clouds).
	 */
	syncToFocus(): void {
		const sysId = this.ctx.focusedSystemId;
		if (!sysId) {
			// Standalone focus (Sun, Ceres, comet…) — no system to load, but if a
			// system was loaded before, queue it for unload so leaving e.g. Jupiter
			// to focus the Sun still releases Jupiter's textures.
			if (this.lastBaryId) {
				this.pendingUnloads.add(this.lastBaryId);
				this.lastBaryId = null;
			}
			return;
		}
		// Resolve to barycenter: if sysId is a planet (e.g. naif-599), its parent is the barycenter.
		const body = this.ctx.getBody(sysId);
		const baryId =
			body?.data.objectType === ObjectType.BARYCENTER ? sysId : (body?.data.parentId ?? sysId);
		if (baryId === this.lastBaryId) return;
		// Queue the prior system for release, then drop the new one out of the
		// pending set in case the user is re-entering it mid-fly.
		if (this.lastBaryId) this.pendingUnloads.add(this.lastBaryId);
		this.pendingUnloads.delete(baryId);
		this.lastBaryId = baryId;
		loadSystemData(
			baryId,
			this.bodyObjects,
			this.scene,
			this.textureLoader,
			this.clock.jd,
			this.renderer.capabilities.maxTextureSize,
			this.ctx
		).then(() => {
			this.onLoaded();
			this.ctx.orientationVersion++;
		});
	}

	/**
	 * Release the GPU textures of any system that was queued for unload by a
	 * prior `syncToFocus`. Caller should gate this on the focus animation
	 * having settled.
	 */
	drainPendingUnloads(): void {
		if (this.pendingUnloads.size === 0) return;
		for (const baryId of this.pendingUnloads) {
			unloadSystemTextures(baryId, this.bodyObjects, this.scene, this.ctx);
		}
		this.pendingUnloads.clear();
	}

	hasPendingUnloads(): boolean {
		return this.pendingUnloads.size > 0;
	}
}
