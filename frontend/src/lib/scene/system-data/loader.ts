import type { Scene, TextureLoader, WebGLRenderer } from 'three';
import { ObjectType } from '$lib/types/objects';
import type { BodyObjects } from '$lib/scene/types';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import type { SimClock } from '$lib/scene/state/clock.svelte';
import { loadSystemData, unloadSystemTextures } from '$lib/scene/objects/construction';

/**
 * Tracks which system's textures + orientation are resident, plus a
 * deferred-unload queue so a focus-fly that reverses mid-way doesn't thrash
 * the GPU. Caller drains via {@link drainPendingUnloads} once the fly settles.
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

	/** On barycenter change, queue the prior system for unload and load the new one. */
	syncToFocus(): void {
		const sysId = this.ctx.focusedSystemId;
		if (!sysId) {
			// Standalone focus (Sun, Ceres, comet…): queue any prior system for unload.
			if (this.lastBaryId) {
				this.pendingUnloads.add(this.lastBaryId);
				this.lastBaryId = null;
			}
			return;
		}
		// Resolve sysId to its barycenter (planet → parent, barycenter → itself).
		const body = this.ctx.getBody(sysId);
		const baryId =
			body?.data.objectType === ObjectType.BARYCENTER ? sysId : (body?.data.parentId ?? sysId);
		if (baryId === this.lastBaryId) return;
		// Drop the new id from pending unloads in case the user re-enters mid-fly.
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
			this.ctx.bodies.orientationVersion++;
		});
	}

	/** Release the GPU textures of every queued system. Gate on focus-fly settled. */
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
