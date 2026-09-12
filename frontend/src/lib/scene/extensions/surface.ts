/**
 * A shape drawn on a body rather than in the space round it: a ground track, a
 * quadrangle, the footprint of an instrument. It is given in longitude and
 * latitude, exactly as the flat map's shapes are, so the same list of places
 * draws on both maps; and it is held in the body's own frame, so it turns with
 * the body as the clock runs.
 *
 * Following the curve is what separates it from a polygon. The line between
 * two places is filled in along the surface before it is drawn, and a filled
 * area is built as rings of triangles running out from its middle, each row
 * put back on the sphere — a flat sheet across the same outline would sink
 * through the ground in the middle.
 */

import {
	BufferGeometry,
	Float32BufferAttribute,
	Group,
	Mesh,
	type Quaternion,
	type ShaderMaterial
} from 'three';
import { bodyQuaternion } from '$lib/math/orientation';
import { kmToScene } from '$lib/math/units';
import { effectiveRadiusKm } from '$lib/types/objects';
import { densify, type Interpolation, type LonLat } from '$lib/flatmap/geometry';
import { buildFatLineFromThin, writeFatTrailVertices } from '$lib/scene/objects/trail/geometry';
import { rotateByQuaternion, surfaceDirection } from './anchor';
import { meanDirection, slerpDirection } from './geometry';
import { makeAreaMaterial } from './material';
import type { ShapeStyle } from './style';
import type { Extension, ExtensionFrame } from './registry';

export interface SurfaceShapeOptions extends ShapeStyle {
	/** Export id of the body it is drawn on. */
	body: string;
	/** The shape in longitude and latitude, degrees. The same list draws on the
	 *  flat map. */
	points: readonly LonLat[];
	/** How the space between the given places is filled: along the parallels
	 *  and meridians, or the short way over the surface. */
	interpolate?: Interpolation;
	/** Degrees of arc per step between the given places. Smaller is smoother
	 *  and slower. */
	stepDeg?: number;
	/** Height above the surface. A little above it by default, so the shape is
	 *  not lost in the surface's own depth; give it a height of its own for a
	 *  track flown rather than walked. */
	altitudeKm?: number;
}

export interface SurfacePolylineOptions extends SurfaceShapeOptions {
	/** Join the last place back to the first. */
	closed?: boolean;
}

export interface SurfacePolygonOptions extends SurfaceShapeOptions {
	/** Filled in its own colour when left out; an area on a body is drawn to be
	 *  seen as one. */
	fill?: string;
}

export interface SurfaceCircleOptions extends ShapeStyle {
	body: string;
	center: LonLat;
	/** Radius as an angle at the body's centre. */
	radiusDeg?: number;
	/** Radius along the surface. Needs the body's radius to be known; ignored
	 *  when it is not. */
	radiusKm?: number;
	steps?: number;
	altitudeKm?: number;
}

/** A shape on a body's surface, for as long as the host keeps it. */
export interface SurfaceShape {
	/** Replace the places, keeping everything else. */
	setPoints(points: readonly LonLat[]): void;
	setVisible(visible: boolean): void;
	remove(): void;
}

/** Height a surface shape floats at when the host names none, as a fraction of
 *  the body's radius: clear of the relief the surface is drawn with — half a
 *  percent is 17 km at Mars, over every volcano but Olympus Mons — and low
 *  enough to read as lying on the ground. */
const DEFAULT_LIFT = 0.005;

/**
 * Drawn after the opaque body but before its atmosphere, whose shell writes
 * depth from outside at render order 2. At the order the trails are drawn at, a
 * shape lying on the ground is under that shell and would be culled by it right
 * across the disc.
 */
const SURFACE_RENDER_ORDER = 1.5;

/** Degrees of arc per row of a filled area, out from its middle. */
const FILL_ROW_DEG = 5;

const MAX_FILL_ROWS = 24;

export class SurfaceShapeExtension implements Extension, SurfaceShape {
	readonly object = new Group();
	private readonly body: string;
	private readonly altitudeKm: number | null;
	private readonly closed: boolean;
	private readonly interpolate: Interpolation;
	private readonly stepDeg: number | undefined;
	private readonly color: string;
	private readonly widthPx: number;
	private readonly opacity: number;
	private readonly fillColor: string | null;
	private readonly fillOpacity: number;
	/** Unit directions of the outline in the body's own frame, before its
	 *  rotation: the shape itself, which never changes as the body turns. */
	private dirs = new Float64Array(0);
	private count = 0;
	private line: Mesh<BufferGeometry, ShaderMaterial> | null = null;
	private scratch = new Float32Array(0);
	private alphas = new Float32Array(0);
	/** Directions of the fill's vertices, in the same frame: the middle first,
	 *  then one row of the outline's length per step out to it. */
	private fanDirs = new Float64Array(0);
	private fill: Mesh<BufferGeometry, ShaderMaterial> | null = null;
	private fillScratch = new Float32Array(0);
	private readonly turned: [number, number, number] = [0, 0, 0];
	private wanted = true;
	private removeSelf: (() => void) | null = null;

	constructor(options: SurfacePolylineOptions) {
		this.body = options.body;
		this.altitudeKm = options.altitudeKm ?? null;
		this.closed = options.closed ?? false;
		this.interpolate = options.interpolate ?? 'linear';
		this.stepDeg = options.stepDeg;
		this.color = options.color ?? '#ffffff';
		this.widthPx = options.widthPx ?? 2;
		this.opacity = options.opacity ?? 1;
		this.fillColor = options.fill ?? null;
		this.fillOpacity = options.fillOpacity ?? 0.25;
		this.object.matrixAutoUpdate = false;
		this.setPoints(options.points);
	}

	/** @internal Called by the map when the shape is added. */
	bind(removeSelf: () => void): void {
		this.removeSelf = removeSelf;
	}

	setPoints(points: readonly LonLat[]): void {
		const walked = densify(points, {
			interpolate: this.interpolate,
			stepDeg: this.stepDeg,
			closed: this.closed
		});
		this.dirs = new Float64Array(walked.length * 3);
		for (let i = 0; i < walked.length; i++) {
			const [x, y, z] = surfaceDirection(walked[i].lat, walked[i].lon);
			this.dirs[i * 3] = x;
			this.dirs[i * 3 + 1] = y;
			this.dirs[i * 3 + 2] = z;
		}
		this.count = walked.length;
		this.buildLine();
		this.buildFill();
	}

	setVisible(visible: boolean): void {
		this.wanted = visible;
	}

	remove(): void {
		this.removeSelf?.();
		this.removeSelf = null;
	}

	update({ jd, basis, camera, ctx }: ExtensionFrame): void {
		const body = this.wanted && this.count >= 2 ? ctx.getBody(this.body) : undefined;
		if (this.line) this.line.visible = body !== undefined;
		if (this.fill) this.fill.visible = body !== undefined;
		if (!body) return;
		const radiusKm = effectiveRadiusKm(body.data);
		const scale = kmToScene(radiusKm + (this.altitudeKm ?? radiusKm * DEFAULT_LIFT));
		// Without orientation metadata the body has no measured spin, so the
		// shape is put on the unrotated sphere rather than nowhere.
		const q = body.orientation ? bodyQuaternion(body.orientation, jd, body.nutPrec) : null;
		const origin: [number, number, number] = [
			body.position[0] - basis[0],
			body.position[1] - basis[1],
			body.position[2] - basis[2]
		];

		if (this.line) {
			this.place(this.dirs, this.count, q, scale, origin, this.scratch);
			writeFatTrailVertices(this.line.geometry, this.scratch, this.alphas, this.alphas, this.count);
			this.line.material.uniforms.uCenterOffset.value.copy(camera.position).negate();
		}
		if (this.fill) {
			const position = this.fill.geometry.getAttribute('position');
			this.place(this.fanDirs, this.fillScratch.length / 3, q, scale, origin, this.fillScratch);
			position.needsUpdate = true;
			this.fill.material.uniforms.uCenterOffset.value.copy(camera.position).negate();
		}
	}

	/** Turn body-fixed directions with the body, put them on its surface and
	 *  shift them into the frame being drawn. */
	private place(
		dirs: Float64Array,
		count: number,
		q: Quaternion | null,
		scale: number,
		origin: [number, number, number],
		out: Float32Array
	): void {
		for (let i = 0; i < count; i++) {
			const at = i * 3;
			if (q) rotateByQuaternion(q, dirs[at], dirs[at + 1], dirs[at + 2], this.turned, 0);
			else {
				this.turned[0] = dirs[at];
				this.turned[1] = dirs[at + 1];
				this.turned[2] = dirs[at + 2];
			}
			out[at] = this.turned[0] * scale + origin[0];
			out[at + 1] = this.turned[1] * scale + origin[1];
			out[at + 2] = this.turned[2] * scale + origin[2];
		}
	}

	private buildLine(): void {
		this.disposeLine();
		if (this.count < 2 || this.widthPx <= 0) return;
		this.scratch = new Float32Array(this.count * 3);
		this.alphas = new Float32Array(this.count).fill(this.opacity);
		const line = buildFatLineFromThin(
			this.count,
			this.scratch,
			this.alphas,
			this.alphas,
			this.count,
			this.color,
			this.widthPx,
			// The host asked for this colour; do not shade it down the way the
			// scene's own trails are.
			1
		);
		// The line's shader places vertices relative to the camera, so three's
		// own frustum test would judge it against a bounding sphere that means
		// nothing here.
		line.frustumCulled = false;
		line.renderOrder = SURFACE_RENDER_ORDER;
		this.object.add(line);
		this.line = line as Mesh<BufferGeometry, ShaderMaterial>;
	}

	/** Rings of triangles from the middle of the shape out to its outline. Each
	 *  row sits on the sphere, so the fill hugs the body however wide it is. */
	private buildFill(): void {
		this.disposeFill();
		if (!this.fillColor || this.count < 3) return;
		const middle = meanDirection(this.dirs, this.count);
		let widest = 0;
		for (let i = 0; i < this.count; i++) {
			const dot =
				middle[0] * this.dirs[i * 3] +
				middle[1] * this.dirs[i * 3 + 1] +
				middle[2] * this.dirs[i * 3 + 2];
			widest = Math.max(widest, Math.acos(Math.min(1, Math.max(-1, dot))));
		}
		const rows = Math.min(
			MAX_FILL_ROWS,
			Math.max(1, Math.ceil((widest * 180) / Math.PI / FILL_ROW_DEG))
		);

		const vertices = 1 + rows * this.count;
		this.fanDirs = new Float64Array(vertices * 3);
		this.fanDirs[0] = middle[0];
		this.fanDirs[1] = middle[1];
		this.fanDirs[2] = middle[2];
		for (let r = 1; r <= rows; r++) {
			for (let i = 0; i < this.count; i++) {
				const edge = [this.dirs[i * 3], this.dirs[i * 3 + 1], this.dirs[i * 3 + 2]];
				const [x, y, z] = slerpDirection(middle, edge, r / rows);
				const at = (1 + (r - 1) * this.count + i) * 3;
				this.fanDirs[at] = x;
				this.fanDirs[at + 1] = y;
				this.fanDirs[at + 2] = z;
			}
		}

		const indices: number[] = [];
		const ring = (r: number, i: number) => 1 + (r - 1) * this.count + i;
		for (let i = 0; i < this.count - 1; i++) indices.push(0, ring(1, i), ring(1, i + 1));
		for (let r = 1; r < rows; r++) {
			for (let i = 0; i < this.count - 1; i++) {
				const a = ring(r, i);
				const b = ring(r, i + 1);
				const c = ring(r + 1, i);
				const d = ring(r + 1, i + 1);
				indices.push(a, c, b, b, c, d);
			}
		}

		const geometry = new BufferGeometry();
		geometry.setAttribute(
			'position',
			new Float32BufferAttribute(new Float32Array(vertices * 3), 3)
		);
		geometry.setIndex(indices);
		this.fillScratch = geometry.getAttribute('position').array as Float32Array<ArrayBuffer>;
		const mesh = new Mesh(geometry, makeAreaMaterial(this.fillColor, this.fillOpacity));
		mesh.matrixAutoUpdate = false;
		mesh.frustumCulled = false;
		mesh.renderOrder = SURFACE_RENDER_ORDER;
		this.object.add(mesh);
		this.fill = mesh as Mesh<BufferGeometry, ShaderMaterial>;
	}

	private disposeLine(): void {
		if (!this.line) return;
		this.object.remove(this.line);
		this.line.geometry.dispose();
		this.line.material.dispose();
		this.line = null;
	}

	private disposeFill(): void {
		if (!this.fill) return;
		this.object.remove(this.fill);
		this.fill.geometry.dispose();
		this.fill.material.dispose();
		this.fill = null;
	}

	dispose(): void {
		this.disposeLine();
		this.disposeFill();
	}
}
