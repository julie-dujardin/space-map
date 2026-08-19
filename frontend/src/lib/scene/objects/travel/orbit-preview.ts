/**
 * The orbits a trip's ends are met in, drawn round their live bodies while the
 * trip is still being put together — the picked orbit at each end, with the
 * row under the pointer standing in while an endpoint's list is up.
 *
 * Unlike the chosen trajectory's end orbits these are not part of a path: they
 * ride the live bodies rather than the frozen transfer frame, and draw at
 * every zoom — the reader is choosing them, so there is no ring-vs-speck gate.
 */

import { Group, Mesh, Scene, Vector3, type ShaderMaterial } from 'three';
import { buildFatLineFromThin, writeFatTrailVertices } from '$lib/scene/objects/trail/geometry';
import { eclipticToScene } from '$lib/math/travel/state';
// Type-only: the kernel is a chunk only /nav should pull in, and this overlay
// is held by the renderer from the first frame.
import type { Vec3 as TravelVec3 } from '$lib/math/travel/vec3';
import type { Vec3 } from '$lib/scene/animation/math';
import { ARC_COLORS } from '$lib/travel/arc-colors';

/** One end's ring, as the panel hands it to the map. */
export interface OrbitPreview {
	/** The live body the ring is drawn round. */
	bodyId: string;
	/** The ring, body-centred ecliptic km — see `endOrbitPreviewRing`. */
	pointsKm: readonly TravelVec3[];
	/** Apoapsis radius, km — what the camera frames to show the whole ring. */
	radiusKm: number;
}

/** The choice being made is the map's subject while the popover is open, so it
 *  takes the plan's own weight rather than the settled rings' thinner one. */
const PREVIEW_WIDTH = 2;
const PREVIEW_BRIGHTNESS = 1;
/** Same shelf as the plan, over the trails it crosses. */
const PREVIEW_RENDER_ORDER = 4;
/** More than `endOrbitPreviewRing` ever sends; extra capacity stays undrawn. */
const CAPACITY = 200;

interface RingSlot {
	line: Mesh;
	bodyId: string;
	local: Float64Array;
	positions: Float32Array;
	alphas: Float32Array;
	count: number;
}

export class OrbitPreviewOverlay {
	private readonly group = new Group();
	/** One slot per end; meshes are pooled and hidden rather than rebuilt — a
	 *  slider drag lands here on every input event. */
	private readonly slots: RingSlot[] = [];
	private shown = 0;
	private layer: number | null = null;

	constructor(scene: Scene) {
		// Vertices carry world offsets, so the group never moves.
		this.group.frustumCulled = false;
		scene.add(this.group);
	}

	get isEmpty(): boolean {
		return this.shown === 0;
	}

	/** Swap in the rings being picked, or clear them all with an empty list. */
	set(previews: readonly OrbitPreview[]): void {
		let at = 0;
		for (const preview of previews) {
			if (preview.pointsKm.length < 2) continue;
			const slot = this.slot(at++);
			slot.bodyId = preview.bodyId;
			slot.count = Math.min(preview.pointsKm.length, CAPACITY);
			for (let i = 0; i < slot.count; i++) {
				const [x, y, z] = eclipticToScene(preview.pointsKm[i]);
				slot.local[i * 3] = x;
				slot.local[i * 3 + 1] = y;
				slot.local[i * 3 + 2] = z;
			}
		}
		this.shown = at;
		for (let i = at; i < this.slots.length; i++) this.slots[i].line.visible = false;
		this.group.visible = at > 0;
		// The shown slots become visible in `reposition`, where their bodies are
		// looked up.
	}

	private slot(index: number): RingSlot {
		while (this.slots.length <= index) {
			const positions = new Float32Array(CAPACITY * 3);
			const alphas = new Float32Array(CAPACITY).fill(1);
			const line = buildFatLineFromThin(
				CAPACITY,
				positions,
				alphas,
				alphas,
				0,
				ARC_COLORS.cruise,
				PREVIEW_WIDTH,
				PREVIEW_BRIGHTNESS
			);
			line.frustumCulled = false;
			line.renderOrder = PREVIEW_RENDER_ORDER;
			if (this.layer !== null) line.layers.set(this.layer);
			this.group.add(line);
			this.slots.push({
				line,
				bodyId: '',
				local: new Float64Array(CAPACITY * 3),
				positions,
				alphas,
				count: 0
			});
		}
		return this.slots[index];
	}

	/** Hide with the rest of the map furniture in immersive mode. */
	setLayer(layer: number): void {
		this.layer = layer;
		this.group.traverse((object) => object.layers.set(layer));
	}

	/** Put each ring on its live body this frame — hidden while that body isn't
	 *  resident, rather than drawn at the origin. */
	reposition(bodyScenePos: (id: string) => Vec3 | null, basis: Vec3): void {
		for (let s = 0; s < this.shown; s++) {
			const slot = this.slots[s];
			const at = bodyScenePos(slot.bodyId);
			slot.line.visible = at !== null;
			if (!at) continue;
			const dx = at[0] - basis[0];
			const dy = at[1] - basis[1];
			const dz = at[2] - basis[2];
			for (let i = 0; i < slot.count; i++) {
				slot.positions[i * 3] = slot.local[i * 3] + dx;
				slot.positions[i * 3 + 1] = slot.local[i * 3 + 1] + dy;
				slot.positions[i * 3 + 2] = slot.local[i * 3 + 2] + dz;
			}
			writeFatTrailVertices(
				slot.line.geometry,
				slot.positions,
				slot.alphas,
				slot.alphas,
				slot.count
			);
		}
	}

	/** Same contract as the trails' per-frame update: the vertices are drawn
	 *  relative to the camera, and the shader adds this back. */
	updateCameraOffset(cameraPosition: Vector3): void {
		for (const slot of this.slots) {
			const material = slot.line.material as ShaderMaterial;
			(material.uniforms.uCenterOffset.value as Vector3).set(
				-cameraPosition.x,
				-cameraPosition.y,
				-cameraPosition.z
			);
		}
	}
}
