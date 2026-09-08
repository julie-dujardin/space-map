/**
 * What a host has added to the map. Each extension resolves its own place in
 * world coordinates and is placed relative to the render origin every frame,
 * which is what lets it survive the origin jumping between bodies.
 */

import { Group, type PerspectiveCamera } from 'three';
import type { Vec3 } from '$lib/scene/animation/math';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';

export interface ExtensionFrame {
	jd: number;
	/** Render origin: world position the scene is currently drawn around. */
	basis: Vec3;
	camera: PerspectiveCamera;
	ctx: ContextManager;
}

/** One added thing. The registry owns the frame loop; the extension owns what
 *  it draws. */
export interface Extension {
	/** Scene objects to add and remove with it. */
	readonly object: Group;
	update(frame: ExtensionFrame): void;
	dispose(): void;
}

export class ExtensionRegistry {
	/** One parent for everything host-added, so it is added and torn down in
	 *  one place and never confused with the scene's own objects. */
	readonly group = new Group();
	private readonly extensions = new Set<Extension>();

	constructor() {
		this.group.matrixAutoUpdate = false;
		this.group.frustumCulled = false;
	}

	add(extension: Extension): void {
		this.extensions.add(extension);
		this.group.add(extension.object);
	}

	remove(extension: Extension): void {
		if (!this.extensions.delete(extension)) return;
		this.group.remove(extension.object);
		extension.dispose();
	}

	update(frame: ExtensionFrame): void {
		for (const extension of this.extensions) extension.update(frame);
	}

	dispose(): void {
		for (const extension of this.extensions) {
			this.group.remove(extension.object);
			extension.dispose();
		}
		this.extensions.clear();
	}
}
