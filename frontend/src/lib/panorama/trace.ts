/**
 * A rover's traverse drawn on the ground of the 3D map, after Google Earth: a
 * ribbon lying in the ground's own plane, a fixed width on screen, with a
 * round dot at every place so its joints are round and the whole traverse
 * still reads as a dot from orbit. Its depth is nudged toward the camera so
 * the ground it lies on never cuts it, while a hill in front of it still
 * does; the far side of the body hides it by fading the vertices past the
 * horizon, where no depth remains to tell.
 *
 * The same placement puts every panorama on screen, so the pointer can be
 * matched to the nearest one: the ribbon is in the scene, which the DOM
 * cannot hit-test.
 */

import {
	BufferAttribute,
	BufferGeometry,
	Color,
	DoubleSide,
	Group,
	Mesh,
	ShaderMaterial,
	Vector3
} from 'three';
import type { PanoramaEntry } from '$lib/fetch/objects/object-data';
import { bodyQuaternion } from '$lib/math/orientation';
import { kmToScene } from '$lib/math/units';
import { rotateByQuaternion, surfaceDirection } from '$lib/scene/extensions/anchor';
import type { Extension, ExtensionFrame } from '$lib/scene/extensions/registry';
import { effectiveRadiusKm } from '$lib/types/objects';

/** Height above the body's mean radius, km, under a place. */
export type GroundKm = (entry: PanoramaEntry) => number;

export interface TraverseTraceOptions {
	body: string;
	/** The panoramas, one run per mission in time order. */
	runs: readonly (readonly PanoramaEntry[])[];
	ground: GroundKm;
	widthPx: number;
	color: string;
}

/** Drawn after the opaque body but before its atmosphere, whose shell writes
 *  depth from outside at render order 2 and would cull a shape lying on the
 *  ground right across the disc. */
const RENDER_ORDER = 1.5;
const DOT_SEGMENTS = 20;
/** How far off the ground the ribbon floats, as a share of its distance from
 *  the camera: under a pixel at any range, and past the depth buffer's
 *  resolution at every range, which a fixed height cannot be from orbit. */
const LIFT = 0.002;

/** Index of the nearest place to (x, y) within `withinPx`, or −1. Places on
 *  the far side of the body are skipped. */
export function nearestOnScreen(
	screen: Float32Array,
	facing: Uint8Array,
	count: number,
	x: number,
	y: number,
	withinPx: number
): number {
	let best = -1;
	let bestD2 = withinPx * withinPx;
	for (let i = 0; i < count; i++) {
		if (!facing[i]) continue;
		const dx = screen[i * 2] - x;
		const dy = screen[i * 2 + 1] - y;
		const d2 = dx * dx + dy * dy;
		if (d2 <= bestD2) {
			best = i;
			bestD2 = d2;
		}
	}
	return best;
}

function makeMaterial(color: string): ShaderMaterial {
	return new ShaderMaterial({
		transparent: true,
		depthWrite: false,
		// Pulled a few depth units toward the camera: the ribbon sits on the
		// terrain it is sampled from, and would otherwise fight it.
		polygonOffset: true,
		polygonOffsetFactor: -2,
		polygonOffsetUnits: -4,
		side: DoubleSide,
		uniforms: { uColor: { value: new Color(color) } },
		vertexShader: `
			attribute float alpha;
			varying float vAlpha;
			void main() {
				vAlpha = alpha;
				gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
			}`,
		fragmentShader: `
			uniform vec3 uColor;
			varying float vAlpha;
			void main() {
				if (vAlpha <= 0.0) discard;
				gl_FragColor = vec4(uColor, vAlpha);
			}`
	});
}

/** One mission's ribbon: a strip two vertices wide along the run, then a fan
 *  at each place. Indices never change; positions and alphas are rewritten
 *  every frame. */
class Run {
	readonly mesh: Mesh<BufferGeometry, ShaderMaterial>;
	readonly count: number;
	/** Body-fixed unit directions of the places, before the body's rotation. */
	readonly dirs: Float64Array;
	readonly positions: Float32Array;
	readonly alphas: Float32Array;
	/** The turned directions, placed this frame: the places themselves. */
	readonly placed: Float64Array;

	constructor(entries: readonly PanoramaEntry[], material: ShaderMaterial) {
		this.count = entries.length;
		this.dirs = new Float64Array(this.count * 3);
		this.placed = new Float64Array(this.count * 3);
		for (let i = 0; i < this.count; i++) {
			const [x, y, z] = surfaceDirection(entries[i].lat, entries[i].lon);
			this.dirs[i * 3] = x;
			this.dirs[i * 3 + 1] = y;
			this.dirs[i * 3 + 2] = z;
		}
		const vertices = this.count * 2 + this.count * (1 + DOT_SEGMENTS);
		this.positions = new Float32Array(vertices * 3);
		this.alphas = new Float32Array(vertices);
		const indices: number[] = [];
		for (let i = 0; i < this.count - 1; i++) {
			const a = i * 2;
			indices.push(a, a + 1, a + 2, a + 1, a + 3, a + 2);
		}
		for (let dot = 0; dot < this.count; dot++) {
			const centre = this.count * 2 + dot * (1 + DOT_SEGMENTS);
			for (let s = 0; s < DOT_SEGMENTS; s++)
				indices.push(centre, centre + 1 + s, centre + 1 + ((s + 1) % DOT_SEGMENTS));
		}
		const geometry = new BufferGeometry();
		// The arrays themselves, not copies: they are rewritten every frame.
		geometry.setAttribute('position', new BufferAttribute(this.positions, 3));
		geometry.setAttribute('alpha', new BufferAttribute(this.alphas, 1));
		geometry.setIndex(indices);
		this.mesh = new Mesh(geometry, material);
		this.mesh.matrixAutoUpdate = false;
		this.mesh.frustumCulled = false;
		this.mesh.renderOrder = RENDER_ORDER;
	}

	dispose(): void {
		this.mesh.geometry.dispose();
	}
}

export class TraverseTrace implements Extension {
	readonly object = new Group();
	/** Screen positions of every panorama, in CSS pixels from the canvas's
	 *  top-left corner, in the order the runs were given. */
	readonly screen: Float32Array;
	/** 1 where the place is on the near side of the body and in front of the
	 *  camera. */
	readonly facing: Uint8Array;
	readonly count: number;
	private readonly entries: PanoramaEntry[];
	private readonly runs: Run[];
	private readonly material: ShaderMaterial;
	private readonly turned: [number, number, number] = [0, 0, 0];
	private readonly v = new Vector3();
	private readonly tangent = new Vector3();
	private readonly side = new Vector3();
	private readonly normal = new Vector3();
	private readonly u = new Vector3();
	/** The body's centre in the frame being drawn. */
	private readonly centre = new Vector3();

	constructor(private readonly options: TraverseTraceOptions) {
		this.material = makeMaterial(options.color);
		this.runs = options.runs.map((run) => new Run(run, this.material));
		for (const run of this.runs) this.object.add(run.mesh);
		this.entries = options.runs.flat();
		this.count = this.entries.length;
		this.screen = new Float32Array(this.count * 2);
		this.facing = new Uint8Array(this.count);
		this.object.matrixAutoUpdate = false;
	}

	nearest(x: number, y: number, withinPx: number): number {
		return nearestOnScreen(this.screen, this.facing, this.count, x, y, withinPx);
	}

	entryAt(index: number): PanoramaEntry {
		return this.entries[index];
	}

	update({ jd, basis, camera, viewportPx, ctx }: ExtensionFrame): void {
		const body = ctx.getBody(this.options.body);
		this.object.visible = body !== undefined;
		if (!body) {
			this.facing.fill(0);
			return;
		}
		const radiusKm = effectiveRadiusKm(body.data);
		const q = body.orientation ? bodyQuaternion(body.orientation, jd, body.nutPrec) : null;
		const origin: [number, number, number] = [
			body.position[0] - basis[0],
			body.position[1] - basis[1],
			body.position[2] - basis[2]
		];
		this.centre.set(origin[0], origin[1], origin[2]);
		// Scene units per pixel at unit distance from the camera, which times a
		// place's distance gives the ribbon's half width there.
		const perPx = (2 * Math.tan((camera.fov * Math.PI) / 360)) / viewportPx;
		const width = viewportPx * camera.aspect;
		const cam = camera.position;

		let at = 0;
		for (const run of this.runs) {
			for (let i = 0; i < run.count; i++) {
				const entry = this.entries[at + i];
				const d = i * 3;
				if (q) rotateByQuaternion(q, run.dirs[d], run.dirs[d + 1], run.dirs[d + 2], this.turned, 0);
				else {
					this.turned[0] = run.dirs[d];
					this.turned[1] = run.dirs[d + 1];
					this.turned[2] = run.dirs[d + 2];
				}
				const scale = kmToScene(radiusKm + this.options.ground(entry));
				run.placed[d] = this.turned[0] * scale + origin[0];
				run.placed[d + 1] = this.turned[1] * scale + origin[1];
				run.placed[d + 2] = this.turned[2] * scale + origin[2];
			}
			this.ribbon(run, perPx, cam);
			for (let i = 0; i < run.count; i++) {
				const d = i * 3;
				this.v.set(run.placed[d], run.placed[d + 1], run.placed[d + 2]);
				const above = run.alphas[i * 2] > 0;
				this.v.project(camera);
				const k = at + i;
				this.facing[k] = above && this.v.z < 1 ? 1 : 0;
				this.screen[k * 2] = ((this.v.x + 1) / 2) * width;
				this.screen[k * 2 + 1] = ((1 - this.v.y) / 2) * viewportPx;
			}
			at += run.count;
		}
	}

	/** Lay the run's strip and dots in the ground's plane at each place: the
	 *  side is across the run and along the ground, the width is what the
	 *  screen asks for at the place's distance, and the alpha goes to zero
	 *  where the ground faces away from the camera. */
	private ribbon(run: Run, perPx: number, cam: Vector3): void {
		const { placed, positions, alphas, count } = run;
		const half = this.options.widthPx / 2;
		for (let i = 0; i < count; i++) {
			const d = i * 3;
			this.v.set(placed[d], placed[d + 1], placed[d + 2]);
			const before = Math.max(0, i - 1) * 3;
			const after = Math.min(count - 1, i + 1) * 3;
			this.tangent.set(
				placed[after] - placed[before],
				placed[after + 1] - placed[before + 1],
				placed[after + 2] - placed[before + 2]
			);
			// The ground's normal, on a sphere: straight out from the centre.
			this.normal.subVectors(this.v, this.centre).normalize();
			// A repeat at the same spot has no direction of its own: it keeps the
			// side of the place before, or any side at all when it is the first.
			if (this.tangent.lengthSq() > 0)
				this.side.crossVectors(this.tangent, this.normal).normalize();
			else if (i === 0) this.side.crossVectors(this.normal, this.u.set(0, 1, 0)).normalize();
			this.u.subVectors(cam, this.v);
			const distance = this.u.length();
			const hw = half * perPx * distance;
			const alpha = this.normal.dot(this.u) > 0 ? 1 : 0;
			this.v.addScaledVector(this.normal, distance * LIFT);
			positions[i * 6] = this.v.x + this.side.x * hw;
			positions[i * 6 + 1] = this.v.y + this.side.y * hw;
			positions[i * 6 + 2] = this.v.z + this.side.z * hw;
			positions[i * 6 + 3] = this.v.x - this.side.x * hw;
			positions[i * 6 + 4] = this.v.y - this.side.y * hw;
			positions[i * 6 + 5] = this.v.z - this.side.z * hw;
			alphas[i * 2] = alpha;
			alphas[i * 2 + 1] = alpha;
			this.dot(run, i, hw, alpha);
		}
		const position = run.mesh.geometry.getAttribute('position');
		const alphaAttr = run.mesh.geometry.getAttribute('alpha');
		position.needsUpdate = true;
		alphaAttr.needsUpdate = true;
	}

	/** A disc in the ground's plane round the place last laid, built on the
	 *  side and the tangent as they stand: the round joint of the strip. */
	private dot(run: Run, which: number, hw: number, alpha: number): void {
		const base = run.count * 2 + which * (1 + DOT_SEGMENTS);
		const { positions, alphas } = run;
		positions[base * 3] = this.v.x;
		positions[base * 3 + 1] = this.v.y;
		positions[base * 3 + 2] = this.v.z;
		alphas[base] = alpha;
		this.tangent.crossVectors(this.normal, this.side).normalize();
		for (let s = 0; s < DOT_SEGMENTS; s++) {
			const a = (s / DOT_SEGMENTS) * Math.PI * 2;
			const c = Math.cos(a) * hw;
			const n = Math.sin(a) * hw;
			const k = (base + 1 + s) * 3;
			positions[k] = this.v.x + this.side.x * c + this.tangent.x * n;
			positions[k + 1] = this.v.y + this.side.y * c + this.tangent.y * n;
			positions[k + 2] = this.v.z + this.side.z * c + this.tangent.z * n;
			alphas[base + 1 + s] = alpha;
		}
	}

	dispose(): void {
		for (const run of this.runs) run.dispose();
		this.material.dispose();
	}
}
