import type { Scene, TextureLoader, WebGLRenderer } from 'three';
import { ObjectType } from '$lib/types/objects';
import type { BodyObjects } from '$lib/scene/types';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import type { SimClock } from '$lib/scene/state/clock.svelte';
import { loadSystemData, unloadSystemTextures } from '$lib/scene/objects/body/system';

/**
 * Tracks which system's textures + orientation are resident, plus a
 * deferred-unload queue so a focus-fly that reverses mid-way doesn't thrash
 * the GPU. Caller drains via {@link drainPendingUnloads} once the fly settles.
 */
export class SystemDataLoader {
	private lastBaryId: string | null = null;
	private readonly pendingUnloads = new Set<string>();
	/** Systems warmed for the approaching trajectory craft, not yet focused. */
	private readonly prefetched = new Set<string>();

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
		const sysId = this.ctx.visibility.focusedSystemId;
		if (!sysId) {
			// Standalone focus (Sun, Ceres, comet…): queue any prior system for unload.
			if (this.lastBaryId) {
				this.pendingUnloads.add(this.lastBaryId);
				this.lastBaryId = null;
			}
			return;
		}
		const baryId = this.resolveBaryId(sysId);
		if (baryId === this.lastBaryId) return;
		// Drop the new id from pending unloads in case the user re-enters mid-fly.
		if (this.lastBaryId) this.pendingUnloads.add(this.lastBaryId);
		this.pendingUnloads.delete(baryId);
		// A warmed system becoming the focus is no longer the prefetch's to unload.
		this.prefetched.delete(baryId);
		this.lastBaryId = baryId;
		this.load(baryId);
	}

	/**
	 * Warm a system the trajectory craft is approaching, ahead of the focus
	 * flip, so entering it doesn't land on white spheres. Balanced by
	 * {@link discardPrefetch} once the approach turns away.
	 */
	prefetch(sysId: string): void {
		const baryId = this.resolveBaryId(sysId);
		if (baryId === this.lastBaryId || this.prefetched.has(baryId)) return;
		this.prefetched.add(baryId);
		this.pendingUnloads.delete(baryId);
		this.load(baryId);
	}

	/** Queue a warmed-but-never-entered system back for unload. */
	discardPrefetch(sysId: string): void {
		const baryId = this.resolveBaryId(sysId);
		if (!this.prefetched.delete(baryId)) return;
		if (baryId !== this.lastBaryId) this.pendingUnloads.add(baryId);
	}

	/** Resolve sysId to its barycenter (planet → parent, barycenter → itself). */
	private resolveBaryId(sysId: string): string {
		const body = this.ctx.getBody(sysId);
		return body?.data.objectType === ObjectType.BARYCENTER ? sysId : (body?.data.parentId ?? sysId);
	}

	private load(baryId: string): void {
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
