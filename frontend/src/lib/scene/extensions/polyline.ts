/**
 * A line a host draws on the map: a trajectory of its own, a boundary, a
 * pointer between two places. It is built like the scene's orbit trails, so it
 * holds its width in pixels at any distance and keeps its precision near a
 * body, and it is placed relative to an anchor that carries it as the anchor
 * moves.
 */

import { Group, Mesh, type ShaderMaterial } from 'three';
import { kmToScene } from '$lib/math/units';
import {
	buildFatLineFromThin,
	writeFatTrailVertices,
	writeLineDistances
} from '$lib/scene/objects/trail/geometry';
import { resolveAnchor, type Anchor, type OffsetKm } from './anchor';
import { SeenLine, parseDash, reachesBehind } from './screen';
import type { Extension, ExtensionFrame } from './registry';

export interface PolylineOptions {
	/** What carries the line: its points are measured from here, so a line
	 *  round a body travels with it. */
	anchor: Anchor;
	/** The line's points in order, kilometres on ecliptic J2000 axes from the
	 *  anchor. Two or more; fewer draws nothing. */
	points: readonly OffsetKm[];
	/** CSS colour name or hex string. White when left out. */
	color?: string;
	/** Width in screen pixels, held at any distance. */
	widthPx?: number;
	/** 0 to 1. */
	opacity?: number;
	/** A dash and a gap in screen pixels, written as the flat map takes them:
	 *  `"4 3"`. Solid when left out. */
	dash?: string;
	/** Fade the line toward its last point, the way an orbit trail fades
	 *  behind a body. */
	fade?: boolean;
	/** Join the last point back to the first. */
	closed?: boolean;
}

export interface Polyline {
	/** Replace the points, keeping everything else. */
	setPoints(points: readonly OffsetKm[]): void;
	/** Move the line onto another place or body. */
	setAnchor(anchor: Anchor): void;
	setVisible(visible: boolean): void;
	remove(): void;
}

/** Scene-unit distance below which a redraw is not worth it: half of the
 *  smallest length a float32 vertex can tell apart at planetary range. */
const REDRAW_EPSILON = 1e-9;

export class PolylineExtension implements Extension, Polyline {
	readonly object = new Group();
	private anchor: Anchor;
	private readonly color: string;
	private readonly widthPx: number;
	private readonly opacity: number;
	private readonly dash: [number, number] | null;
	private readonly fade: boolean;
	private readonly closed: boolean;
	/** Points in scene units relative to the anchor, in float64: the source
	 *  the float32 vertex buffer is written from every time it moves. */
	private local: Float64Array;
	private count = 0;
	private mesh: Mesh<Mesh['geometry'], ShaderMaterial> | null = null;
	/** Points as the fat-line expander wants them: one float32 triple each,
	 *  before it duplicates them into the side pairs it draws. */
	private scratch = new Float32Array(0);
	private alphas = new Float32Array(0);
	private readonly seen = new SeenLine();
	private capacity = 0;
	private lastOrigin: [number, number, number] = [0, 0, 0];
	private dirty = true;
	private wanted = true;
	private removeSelf: (() => void) | null = null;

	constructor(options: PolylineOptions) {
		this.anchor = options.anchor;
		this.color = options.color ?? '#ffffff';
		this.widthPx = options.widthPx ?? 2;
		this.opacity = options.opacity ?? 1;
		this.dash = parseDash(options.dash);
		this.fade = options.fade ?? false;
		this.closed = options.closed ?? false;
		this.local = new Float64Array(0);
		this.object.matrixAutoUpdate = false;
		this.setPoints(options.points);
	}

	/** @internal Called by the map when the line is added. */
	bind(removeSelf: () => void): void {
		this.removeSelf = removeSelf;
	}

	setPoints(points: readonly OffsetKm[]): void {
		const count = points.length + (this.closed && points.length > 2 ? 1 : 0);
		if (this.local.length < count * 3) this.local = new Float64Array(count * 3);
		for (let i = 0; i < points.length; i++) {
			const [x, y, z] = points[i];
			// Ecliptic axes to the scene's: +z is up, +y runs the other way.
			this.local[i * 3] = kmToScene(x);
			this.local[i * 3 + 1] = kmToScene(z);
			this.local[i * 3 + 2] = kmToScene(-y);
		}
		if (count > points.length) this.local.copyWithin(points.length * 3, 0, 3);
		this.count = count;
		if (this.alphas.length < count) {
			this.scratch = new Float32Array(count * 3);
			this.alphas = new Float32Array(count);
		}
		if (count > this.capacity) this.rebuild(count);
		this.fillAlphas();
		// The vertex buffer still holds the previous points.
		this.dirty = true;
	}

	/** Alpha per point, over the points there actually are: a shorter line has
	 *  to fade over its own length, not over the buffer's. */
	private fillAlphas(): void {
		const n = this.count;
		for (let i = 0; i < n; i++) {
			this.alphas[i] = this.fade && n > 1 ? this.opacity * (1 - i / (n - 1)) : this.opacity;
		}
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

	update({ jd, basis, camera, viewportPx, ctx }: ExtensionFrame): void {
		const world = this.wanted && this.count >= 2 ? resolveAnchor(this.anchor, ctx, jd) : null;
		if (this.mesh) this.mesh.visible = world !== null;
		if (!this.mesh || !world) return;
		const origin: [number, number, number] = [
			world[0] - basis[0],
			world[1] - basis[1],
			world[2] - basis[2]
		];
		const moved =
			this.dirty ||
			Math.abs(origin[0] - this.lastOrigin[0]) > REDRAW_EPSILON ||
			Math.abs(origin[1] - this.lastOrigin[1]) > REDRAW_EPSILON ||
			Math.abs(origin[2] - this.lastOrigin[2]) > REDRAW_EPSILON;
		if (moved) {
			for (let i = 0; i < this.count * 3; i++) this.scratch[i] = this.local[i] + origin[i % 3];
			this.lastOrigin = origin;
		}
		// Dashes are counted on screen and a line through the camera is cut at
		// it, so either is drawn again whenever the camera moves.
		const cut = this.dash !== null || reachesBehind(this.scratch, this.count, camera);
		if (cut) {
			const { seen } = this;
			seen.see(this.scratch, this.alphas, this.count, camera, viewportPx);
			if (seen.count > this.capacity) this.rebuild(seen.count);
			writeFatTrailVertices(this.mesh.geometry, seen.points, seen.alphas, seen.alphas, seen.count);
			if (this.dash) writeLineDistances(this.mesh.geometry, seen.lengths, seen.count);
		} else if (moved) {
			writeFatTrailVertices(this.mesh.geometry, this.scratch, this.alphas, this.alphas, this.count);
		}
		this.dirty = cut;
		const mesh = this.mesh;
		// The line's shader is camera-relative, which is what keeps a
		// kilometre-scale line steady when the camera is an astronomical unit out.
		mesh.material.uniforms.uCenterOffset.value.copy(camera.position).negate();
	}

	/** (Re)build the geometry: it is sized once, so a longer line needs a new
	 *  one. The material's colour and width do not change with it. */
	private rebuild(capacity: number): void {
		this.disposeMesh();
		this.dirty = true;
		const mesh = buildFatLineFromThin(
			capacity,
			this.scratch,
			this.alphas,
			this.alphas,
			0,
			this.color,
			this.widthPx,
			// The host asked for this colour; do not shade it down the way the
			// scene's own trails are.
			1,
			this.dash ?? undefined
		);
		// The line's shader places vertices relative to the camera, so three's
		// own frustum test would judge it against a bounding sphere that means
		// nothing here.
		mesh.frustumCulled = false;
		this.object.add(mesh);
		this.mesh = mesh as Mesh<Mesh['geometry'], ShaderMaterial>;
		this.capacity = capacity;
	}

	private disposeMesh(): void {
		const mesh = this.mesh;
		if (!mesh) return;
		this.object.remove(mesh);
		mesh.geometry.dispose();
		mesh.material.dispose();
		this.mesh = null;
	}

	dispose(): void {
		this.disposeMesh();
	}
}
