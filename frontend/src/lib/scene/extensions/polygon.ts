/**
 * An area a host draws on the map: a footprint in space, a region a mission
 * covers, the face of a body a beam falls on. The outline is a polyline, so it
 * holds its width in pixels at any distance; the fill is a sheet of triangles
 * cut from that outline and drawn the same camera-relative way.
 *
 * Like a polyline, an area is measured from an anchor and travels with it. The
 * points do not turn with the body under them — a region that has to do that
 * is a surface shape.
 */

import { BufferGeometry, Float32BufferAttribute, Group, Mesh, type ShaderMaterial } from 'three';
import { kmToScene } from '$lib/math/units';
import { resolveAnchor, type Anchor, type OffsetKm } from './anchor';
import { triangulate } from './geometry';
import { makeAreaMaterial } from './material';
import { PolylineExtension } from './polyline';
import type { Shape, ShapeStyle } from './style';
import type { Extension, ExtensionFrame } from './registry';

export interface PolygonOptions extends ShapeStyle {
	/** What carries the area: its points are measured from here. */
	anchor: Anchor;
	/** The outline in order, kilometres on ecliptic J2000 axes from the anchor.
	 *  The last point joins back to the first; three or more, and fewer draws
	 *  nothing. */
	points: readonly OffsetKm[];
}

export interface Polygon extends Shape {
	/** Replace the outline, keeping everything else. */
	setPoints(points: readonly OffsetKm[]): void;
}

/** How solid an area is when the host names no fill opacity: enough to read as
 *  an area, thin enough to read the map through. */
const DEFAULT_FILL_OPACITY = 0.25;

/** Scene-unit distance below which a redraw is not worth it: half of the
 *  smallest length a float32 vertex can tell apart at planetary range. */
const REDRAW_EPSILON = 1e-9;

/** Drawn with the scene's trails rather than over them: a host's area belongs
 *  in the same layer as the orbits it is talking about. */
const AREA_RENDER_ORDER = 3;

export class PolygonExtension implements Extension, Polygon {
	readonly object = new Group();
	private anchor: Anchor;
	private readonly outline: PolylineExtension | null;
	private readonly fillColor: string | null;
	private readonly fillOpacity: number;
	/** Points in scene units relative to the anchor, in float64: the source the
	 *  float32 vertex buffer is written from every time it moves. */
	private local = new Float64Array(0);
	private count = 0;
	private mesh: Mesh<BufferGeometry, ShaderMaterial> | null = null;
	private scratch = new Float32Array(0);
	private lastOrigin: [number, number, number] = [0, 0, 0];
	private dirty = true;
	private wanted = true;
	private removeSelf: (() => void) | null = null;

	constructor(options: PolygonOptions) {
		this.anchor = options.anchor;
		const widthPx = options.widthPx ?? 2;
		this.fillColor = options.fill ?? null;
		this.fillOpacity = options.fillOpacity ?? DEFAULT_FILL_OPACITY;
		this.outline =
			widthPx > 0
				? new PolylineExtension({
						anchor: options.anchor,
						points: options.points,
						color: options.color,
						widthPx,
						opacity: options.opacity,
						closed: true
					})
				: null;
		if (this.outline) this.object.add(this.outline.object);
		this.object.matrixAutoUpdate = false;
		this.setPoints(options.points);
	}

	/** @internal Called by the map when the area is added. */
	bind(removeSelf: () => void): void {
		this.removeSelf = removeSelf;
	}

	setPoints(points: readonly OffsetKm[]): void {
		this.outline?.setPoints(points);
		if (this.local.length < points.length * 3) this.local = new Float64Array(points.length * 3);
		for (let i = 0; i < points.length; i++) {
			const [x, y, z] = points[i];
			// Ecliptic axes to the scene's: +z is up, +y runs the other way.
			this.local[i * 3] = kmToScene(x);
			this.local[i * 3 + 1] = kmToScene(z);
			this.local[i * 3 + 2] = kmToScene(-y);
		}
		this.count = points.length;
		this.rebuild(points);
	}

	setAnchor(anchor: Anchor): void {
		this.anchor = anchor;
		this.outline?.setAnchor(anchor);
	}

	setVisible(visible: boolean): void {
		this.wanted = visible;
		this.outline?.setVisible(visible);
	}

	remove(): void {
		this.removeSelf?.();
		this.removeSelf = null;
	}

	update(frame: ExtensionFrame): void {
		this.outline?.update(frame);
		const mesh = this.mesh;
		if (!mesh) return;
		const { jd, basis, camera, ctx } = frame;
		const world = this.wanted ? resolveAnchor(this.anchor, ctx, jd) : null;
		mesh.visible = world !== null;
		if (!world) return;
		const origin: [number, number, number] = [
			world[0] - basis[0],
			world[1] - basis[1],
			world[2] - basis[2]
		];
		if (
			this.dirty ||
			Math.abs(origin[0] - this.lastOrigin[0]) > REDRAW_EPSILON ||
			Math.abs(origin[1] - this.lastOrigin[1]) > REDRAW_EPSILON ||
			Math.abs(origin[2] - this.lastOrigin[2]) > REDRAW_EPSILON
		) {
			const position = mesh.geometry.getAttribute('position');
			for (let i = 0; i < this.count * 3; i += 3) {
				this.scratch[i] = this.local[i] + origin[0];
				this.scratch[i + 1] = this.local[i + 1] + origin[1];
				this.scratch[i + 2] = this.local[i + 2] + origin[2];
			}
			position.needsUpdate = true;
			this.lastOrigin = origin;
			this.dirty = false;
		}
		mesh.material.uniforms.uCenterOffset.value.copy(camera.position).negate();
	}

	/** (Re)cut the fill. The outline decides the triangles, so a new outline
	 *  needs new ones. */
	private rebuild(points: readonly OffsetKm[]): void {
		this.disposeMesh();
		this.dirty = true;
		const fill = this.fillColor;
		if (!fill) return;
		const indices = triangulate(points);
		if (!indices.length) return;
		const geometry = new BufferGeometry();
		geometry.setAttribute(
			'position',
			new Float32BufferAttribute(new Float32Array(points.length * 3), 3)
		);
		geometry.setIndex(indices);
		// The attribute owns its own copy of the array, so the per-frame writes
		// have to go into that one.
		this.scratch = geometry.getAttribute('position').array as Float32Array<ArrayBuffer>;
		const mesh = new Mesh(geometry, makeAreaMaterial(fill, this.fillOpacity));
		mesh.matrixAutoUpdate = false;
		mesh.renderOrder = AREA_RENDER_ORDER;
		// The shader places vertices relative to the camera, so three's own
		// frustum test would judge the area against a bounding sphere that means
		// nothing here.
		mesh.frustumCulled = false;
		this.object.add(mesh);
		this.mesh = mesh as Mesh<BufferGeometry, ShaderMaterial>;
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
		this.outline?.dispose();
	}
}
