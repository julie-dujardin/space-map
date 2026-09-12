/**
 * Objects of the host's own: a spacecraft, a station, a body the map has never
 * heard of, drawn with the host's mesh and moved by the host's trajectory.
 *
 * What one is: a place on the map, a thing drawn at it, and a name for it. It
 * is not a body. The map's own objects come from the published export, and
 * everything that reads that catalogue — `getBody`, `flyTo`, a click on the
 * map, the orbit trails, the search a page builds over them — knows nothing of
 * a host object. What it does take part in is the drawing: it is placed in the
 * scene beside the bodies, so a body in front of it hides it and it hides what
 * is behind it, and it holds its place as the map's origin jumps from body to
 * body.
 *
 * The model is the host's. The SDK ships no loader: a mesh arrives as a
 * three.js `Object3D`, already built.
 */

import { Box3, Group, Vector3, type Object3D, type PerspectiveCamera } from 'three';
import { kmToScene } from '$lib/math/units';
import { resolveAnchor, type Anchor } from './anchor';
import { LabelExtension } from './label';
import type { Extension, ExtensionFrame, ExtensionRegistry } from './registry';

export interface MapObjectModel {
	/** The host's own three.js object, added to the map's scene as it is. The
	 *  map never loads one: build it, or load it with a loader of your own. */
	object3d: Object3D;
	/** How big it is drawn, in metres across its longest dimension — the real
	 *  size of the craft, arrays and booms deployed. Drawn in the units the
	 *  object3d was built in when left out. */
	scaleM?: number;
	/** Never draw it smaller than this many pixels across. A twelve-metre
	 *  satellite is nothing at all from a planetary view; this keeps it
	 *  visible, at the cost of its true size. */
	minPx?: number;
}

export interface MapObjectOptions {
	/** The host's own id, unique on this map. One is made up when left out. */
	id?: string;
	/** What it is called, for the label and for the host's own use. */
	name?: string;
	/** Where it is, at any date: a fixed place, or a trajectory. */
	position: Anchor;
	model?: MapObjectModel;
	/** Write the name beside it, in the map's own way of drawing a label. */
	label?: boolean;
	/** Hide the label while the object is behind the body it is measured from.
	 *  The model is hidden by the body itself, whatever this says. */
	occludeLabel?: boolean;
}

/** A host's object on the map, for as long as the host keeps it. */
export interface MapObject {
	readonly id: string;
	readonly name: string | null;
	/** Where it is, as the anchor it was given — hand it to a camera hold to
	 *  follow the object, or to a drawing to hang something off it. */
	readonly position: Anchor;
	/** Kilometres from the body it is measured from, on ecliptic J2000 axes, at
	 *  `jd`. Null where the trajectory says nothing; a fixed place on a surface
	 *  answers null too, since it is not measured as an offset. */
	positionKm(jd: number): readonly [number, number, number] | null;
	/** Move it, including onto another body or another trajectory. */
	setPosition(position: Anchor): void;
	setVisible(visible: boolean): void;
	remove(): void;
}

export class MapObjectExtension implements Extension, MapObject {
	readonly object = new Group();
	readonly id: string;
	readonly name: string | null;
	private anchor: Anchor;
	private readonly model: Object3D | null;
	/** What the model is drawn at to be its true size, and how far across it
	 *  then is in scene units — the pixel floor is measured against that. */
	private readonly trueScale: number;
	private readonly spanScene: number;
	private readonly minPx: number;
	private readonly label: LabelExtension | null;
	private wanted = true;
	private removeSelf: (() => void) | null = null;

	constructor(options: MapObjectOptions, id: string, canvas: HTMLCanvasElement) {
		this.id = id;
		this.name = options.name ?? null;
		this.anchor = options.position;
		this.object.matrixAutoUpdate = false;
		this.object.frustumCulled = false;

		const model = options.model;
		this.model = model?.object3d ?? null;
		this.minPx = model?.minPx ?? 0;
		const span = model ? measureSpan(model.object3d) : 0;
		this.trueScale =
			model?.scaleM !== undefined && span > 0 ? kmToScene(model.scaleM / 1000) / span : 1;
		this.spanScene = span * this.trueScale;
		if (this.model) this.object.add(this.model);

		this.label =
			options.label && this.name
				? new LabelExtension(
						{
							anchor: options.position,
							text: this.name,
							// Above the object rather than over it.
							align: [0.5, 1.4],
							occlude: options.occludeLabel
						},
						canvas
					)
				: null;
		if (this.label) this.object.add(this.label.object);
	}

	/** @internal Called by the map when the object is added. */
	bind(removeSelf: () => void): void {
		this.removeSelf = removeSelf;
	}

	get position(): Anchor {
		return this.anchor;
	}

	positionKm(jd: number): readonly [number, number, number] | null {
		const anchor = this.anchor;
		if ('latitude' in anchor) return null;
		const offset = typeof anchor.offsetKm === 'function' ? anchor.offsetKm(jd) : anchor.offsetKm;
		// No offset is the body's centre, not an unknown place.
		return offset === undefined ? [0, 0, 0] : offset;
	}

	setPosition(position: Anchor): void {
		this.anchor = position;
		this.label?.setAnchor(position);
	}

	setVisible(visible: boolean): void {
		this.wanted = visible;
		this.label?.setVisible(visible);
	}

	remove(): void {
		this.removeSelf?.();
		this.removeSelf = null;
	}

	update(frame: ExtensionFrame): void {
		const { basis, camera, jd, ctx } = frame;
		const model = this.model;
		const world = this.wanted ? resolveAnchor(this.anchor, ctx, jd) : null;
		this.label?.update(frame);
		if (!model) return;
		model.visible = world !== null;
		if (!world) return;
		model.position.set(world[0] - basis[0], world[1] - basis[1], world[2] - basis[2]);
		const scale = this.drawnScale(model.position, camera, frame.viewportPx);
		model.scale.setScalar(scale);
		model.updateMatrixWorld(true);
	}

	/** True size, held to a floor in pixels when the host asked for one. */
	private drawnScale(position: Vector3, camera: PerspectiveCamera, viewportPx: number): number {
		if (this.minPx <= 0 || this.spanScene <= 0) return this.trueScale;
		const distance = camera.position.distanceTo(position);
		if (distance <= 0) return this.trueScale;
		// Pixels a scene unit covers at that distance, under the projection the
		// camera is drawn with.
		const perUnit = viewportPx / (2 * Math.tan((camera.fov * Math.PI) / 180 / 2) * distance);
		const drawnPx = this.spanScene * perUnit;
		return drawnPx >= this.minPx ? this.trueScale : this.trueScale * (this.minPx / drawnPx);
	}

	/** The model belongs to the host, so it is only taken back out of the
	 *  scene: its geometry and materials are the host's to dispose. */
	dispose(): void {
		this.label?.dispose();
		if (this.model) this.object.remove(this.model);
	}
}

/** How far `object3d` reaches across its longest dimension, in its own units. */
function measureSpan(object3d: Object3D): number {
	const size = new Box3().setFromObject(object3d).getSize(new Vector3());
	return Math.max(size.x, size.y, size.z);
}

/**
 * The objects a host has put on the map, by id. Adding one draws it from the
 * next frame; removing one takes it away with whatever it drew.
 */
export interface MapObjects {
	/** Put an object on the map. An id already in use is replaced, so a host
	 *  driving the collection from its own state does not double up. */
	add(options: MapObjectOptions): MapObject;
	get(id: string): MapObject | undefined;
	/** Every object on the map, in the order they were added. */
	all(): MapObject[];
	/** Take them all away. The map's own drawings are left alone. */
	clear(): void;
}

export class MapObjectCollection implements MapObjects {
	private readonly byId = new Map<string, MapObjectExtension>();
	private nextId = 1;

	constructor(
		private readonly registry: () => ExtensionRegistry,
		private readonly canvas: () => HTMLCanvasElement
	) {}

	/** Put an object on the map. An id already in use is replaced, so a host
	 *  driving the collection from its own state does not double up. */
	add(options: MapObjectOptions): MapObject {
		const id = options.id ?? `object-${this.nextId++}`;
		this.byId.get(id)?.remove();
		const object = new MapObjectExtension(options, id, this.canvas());
		const registry = this.registry();
		object.bind(() => {
			this.byId.delete(id);
			registry.remove(object);
		});
		this.byId.set(id, object);
		registry.add(object);
		return object;
	}

	get(id: string): MapObject | undefined {
		return this.byId.get(id);
	}

	/** Every object on the map, in the order they were added. */
	all(): MapObject[] {
		return [...this.byId.values()];
	}

	/** Take them all away. The map's own drawings are left alone. */
	clear(): void {
		for (const object of [...this.byId.values()]) object.remove();
	}
}
