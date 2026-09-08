/**
 * A host's own element pinned to a place on the map. It rides the same layer
 * as the scene's labels, so it is drawn in the map's own stacking order and
 * pans with it, and it can hide itself when the place it marks turns away
 * behind its body.
 */

import { Group } from 'three';
import { CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import { attachCanvasForwarders } from '$lib/scene/label/forward';
import type { Vec3 } from '$lib/scene/animation/math';
import { anchorNormal, resolveAnchor, type Anchor } from './anchor';
import type { Extension, ExtensionFrame } from './registry';

export interface MarkerOptions {
	anchor: Anchor;
	/** The host's element. It is moved into the map's label layer as it is,
	 *  keeping its own classes and listeners. */
	element: HTMLElement;
	/** Which point of the element sits on the anchor, 0 to 1 in its own box.
	 *  Defaults to its centre. */
	align?: readonly [number, number];
	/** Hide the marker when its place has turned to the far side of the body
	 *  it sits on. Only that body is tested, never another one in front. */
	occlude?: boolean;
}

/** A marker on the map, for as long as the host keeps it. */
export interface Marker {
	readonly element: HTMLElement;
	/** Move it, including onto another body. */
	setAnchor(anchor: Anchor): void;
	/** Show or hide it without giving up its place. */
	setVisible(visible: boolean): void;
	remove(): void;
}

export class MarkerExtension implements Extension, Marker {
	readonly object = new Group();
	readonly element: HTMLElement;
	private readonly label: CSS2DObject;
	private anchor: Anchor;
	private readonly occlude: boolean;
	private wanted = true;
	private removeSelf: (() => void) | null = null;

	constructor(options: MarkerOptions, canvas: HTMLCanvasElement) {
		this.anchor = options.anchor;
		this.occlude = options.occlude ?? false;
		this.element = options.element;
		this.label = new CSS2DObject(options.element);
		const [x, y] = options.align ?? [0.5, 0.5];
		this.label.center.set(x, y);
		this.object.add(this.label);
		this.object.matrixAutoUpdate = false;
		// A drag that starts on the marker should still turn the camera, the
		// way it does on the scene's own labels. The listeners go with the
		// element when it is removed.
		attachCanvasForwarders(options.element, canvas);
	}

	/** @internal Called by the map when the marker is added. */
	bind(removeSelf: () => void): void {
		this.removeSelf = removeSelf;
	}

	setAnchor(anchor: Anchor): void {
		this.anchor = anchor;
	}

	setVisible(visible: boolean): void {
		this.wanted = visible;
	}

	remove(): void {
		this.removeSelf?.();
		this.removeSelf = null;
	}

	update(frame: ExtensionFrame): void {
		const { jd, basis, ctx } = frame;
		const world = this.wanted ? resolveAnchor(this.anchor, ctx, jd) : null;
		if (!world) {
			this.label.visible = false;
			return;
		}
		const x = world[0] - basis[0];
		const y = world[1] - basis[1];
		const z = world[2] - basis[2];
		this.label.position.set(x, y, z);
		this.label.visible = this.occlude ? this.facesCamera(world, frame) : true;
		this.object.updateMatrixWorld(true);
	}

	/** The place is on the near side when the camera is above its horizon. */
	private facesCamera(world: Vec3, { camera, ctx }: ExtensionFrame): boolean {
		const normal = anchorNormal(this.anchor, world, ctx);
		if (!normal) return true;
		const { position } = this.label;
		const dx = camera.position.x - position.x;
		const dy = camera.position.y - position.y;
		const dz = camera.position.z - position.z;
		return normal[0] * dx + normal[1] * dy + normal[2] * dz > 0;
	}

	dispose(): void {
		this.label.removeFromParent();
		this.element.remove();
	}
}
