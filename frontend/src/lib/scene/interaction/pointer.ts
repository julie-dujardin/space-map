import {
	Raycaster,
	Vector2,
	Vector3,
	type Intersection,
	type Mesh,
	type Object3D,
	type PerspectiveCamera,
	type Points
} from 'three';
import type { PositionedBody } from '$lib/types/objects';
import type { FocusState } from '$lib/scene/animation/focus';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import type { SimClock } from '$lib/scene/state/clock.svelte';
import { refreshMinorBodyPosition } from '$lib/scene/minor-body-position';
import { pickMoonDot } from './picking';
import type { GpuPickPass } from './gpu-pick';
import type { PickRegistry } from './pick-registry';

const CLICK_DRAG_PX2 = 9; // 3px move tolerance — anything larger reads as a drag, not a click.

/** One resolved point-cloud candidate, comparable to a moon CPU hit. */
interface PointHit {
	body: PositionedBody;
	/** Scene-unit distance from the camera (for depth tie-breaks vs mesh hits). */
	distance: number;
	/** CSS-px distance from the cursor (primary ranking). */
	screenDist: number;
}

/** Pointer-down/up handlers that distinguish a click from a drag and pick the
 *  topmost body under the cursor. Moons and meshes resolve on the CPU; the
 *  asteroid/spacecraft clouds resolve on the GPU via {@link GpuPickPass}. */
export class PointerInteraction {
	private readonly downPos = new Vector2();
	private readonly pointer = new Vector2();
	private readonly _tmpPointer = new Vector2();
	private readonly raycaster = new Raycaster();
	private readonly _tmpV3 = new Vector3();

	constructor(
		private readonly canvas: HTMLCanvasElement,
		private readonly camera: PerspectiveCamera,
		private readonly ctx: ContextManager,
		private readonly clock: SimClock,
		private readonly focus: FocusState,
		private readonly clickables: Mesh[],
		private readonly meshToBody: Map<Mesh, PositionedBody>,
		private readonly onPick: (body: PositionedBody) => void,
		/** Focused body when the NDC ray hits its overlay model, else null. The
		 *  overlay composites over the whole main scene, so such a ray must both
		 *  resolve to the focused body and occlude every pick behind it. */
		private readonly modelPick: (ndcX: number, ndcY: number) => PositionedBody | null,
		private readonly gpuPick: GpuPickPass,
		/** Live asteroid + spacecraft clouds to render in the GPU pick pass. */
		private readonly getClouds: () => Iterable<Points>,
		private readonly pickRegistry: PickRegistry
	) {}

	attach(): void {
		this.canvas.addEventListener('pointerdown', this.onDown);
		this.canvas.addEventListener('pointerup', this.onUp);
	}

	detach(): void {
		this.canvas.removeEventListener('pointerdown', this.onDown);
		this.canvas.removeEventListener('pointerup', this.onUp);
	}

	private onDown = (e: PointerEvent): void => {
		this.downPos.set(e.clientX, e.clientY);
	};

	private onUp = (e: PointerEvent): void => {
		const dx = e.clientX - this.downPos.x;
		const dy = e.clientY - this.downPos.y;
		if (dx * dx + dy * dy > CLICK_DRAG_PX2) return;

		const rect = this.canvas.getBoundingClientRect();
		this.pointer.set(
			((e.clientX - rect.left) / rect.width) * 2 - 1,
			-((e.clientY - rect.top) / rect.height) * 2 + 1
		);

		// The focused body's overlay model draws over everything — a hit wins
		// outright (the hidden sphere only covers part of an irregular model's
		// silhouette, so clicks on its lobes would otherwise fall through to
		// far-off dots behind it).
		const modelBody = this.modelPick(this.pointer.x, this.pointer.y);
		if (modelBody) {
			this.onPick(modelBody);
			return;
		}

		this.raycaster.setFromCamera(this.pointer, this.camera);

		// Mesh under the cursor — the planet you clicked. Only a fallback: a
		// point-cloud body always wins so small dots stay clickable (esp. touch).
		const meshBody = this.resolveMeshHit(this.raycaster.intersectObjects(this.clickables))?.body;

		// Moon dots (CPU — few hundred) and asteroid/spacecraft dots (GPU pick
		// pass). The nearer-to-cursor of the two wins, depth breaking ties, so a
		// clicked moon still outranks an asteroid dot drifting behind it.
		const moonHit = pickMoonDot(
			this.pointer,
			this.camera,
			this.ctx,
			this.focus.focusTruePos,
			this.canvas.clientWidth,
			this.canvas.clientHeight,
			this._tmpV3,
			this.clock.jd,
			e.pointerType,
			this.isDotVisible
		);
		const gpuHit = this.gpuPickCloud(e, rect);
		const pointHit = this.nearer(moonHit, gpuHit);

		const bestBody = pointHit?.body ?? meshBody;
		if (bestBody) this.onPick(bestBody);
	};

	/** Nearer of two point-cloud candidates: smaller cursor distance wins, depth
	 *  breaks ties — matching the CPU picker's ranking across dot sources. */
	private nearer(a: PointHit | null, b: PointHit | null): PointHit | null {
		if (!a) return b;
		if (!b) return a;
		if (b.screenDist < a.screenDist) return b;
		if (b.screenDist === a.screenDist && b.distance < a.distance) return b;
		return a;
	}

	/** GPU-pick the asteroid/spacecraft clouds, then resolve the nearest candidate
	 *  that isn't hidden behind a mesh on its own ray. */
	private gpuPickCloud(e: PointerEvent, rect: DOMRect): PointHit | null {
		const radius = e.pointerType === 'touch' || e.pointerType === 'pen' ? 48 : 24;
		const jd = this.clock.jd;
		const candidates = this.gpuPick.pick(
			this.getClouds(),
			this.camera,
			e.clientX,
			e.clientY,
			rect,
			radius
		);
		for (const c of candidates) {
			const bodyId = this.pickRegistry.resolve(c.pickId);
			if (!bodyId) continue;
			const body = this.ctx.getBody(bodyId);
			if (!body) continue;
			// Advance the CPU copy to the current jd so its position matches the
			// rendered dot (and feeds the focus animation), mirroring the CPU picker.
			refreshMinorBodyPosition(body, jd, this.ctx);
			const worldDist = this.worldDistOf(body);
			if (!this.isDotVisible(c.ndcX, c.ndcY, worldDist)) continue; // occluded — try next
			return { body, distance: worldDist, screenDist: c.pixelDist };
		}
		return null;
	}

	/** Scene-unit distance from the camera to a body's rendered position. */
	private worldDistOf(body: PositionedBody): number {
		const [fx, fy, fz] = this.focus.focusTruePos;
		const cam = this.camera.position;
		return Math.hypot(
			body.position[0] - fx - cam.x,
			body.position[1] - fy - cam.y,
			body.position[2] - fz - cam.z
		);
	}

	/** First raycast hit that resolves to a body. Walks parents so child meshes
	 *  (cloud shells, nomenclature labels) resolve to their planet. */
	private resolveMeshHit(
		hits: Intersection[]
	): { body: PositionedBody; distance: number } | undefined {
		for (const hit of hits) {
			let obj: Object3D | null = hit.object;
			while (obj && !this.meshToBody.has(obj as Mesh)) obj = obj.parent;
			const body = obj ? this.meshToBody.get(obj as Mesh) : undefined;
			if (body) return { body, distance: hit.distance };
		}
		return undefined;
	}

	/** A dot is visible unless a solid mesh — or the focused body's overlay
	 *  model, which composites over the main scene — sits in front of it on its
	 *  own ray. Non-recursive: only the depth-writing surface spheres occlude,
	 *  not their transparent cloud/atmosphere shells. */
	private isDotVisible = (ndcX: number, ndcY: number, worldDist: number): boolean => {
		if (this.modelPick(ndcX, ndcY)) return false;
		if (this.clickables.length === 0) return true;
		this._tmpPointer.set(ndcX, ndcY);
		this.raycaster.setFromCamera(this._tmpPointer, this.camera);
		const hits = this.raycaster.intersectObjects(this.clickables, false);
		return hits.length === 0 || hits[0].distance >= worldDist * 0.999;
	};
}
