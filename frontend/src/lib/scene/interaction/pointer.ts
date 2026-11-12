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
import { attachedModelRoots } from '$lib/scene/objects/body/model';
import {
	isCoarsePointer,
	pickMoonDot,
	pickPlanetDot,
	pickRadiusPx,
	pickSystemDot,
	type DotPick
} from './picking';
import type { GpuPickPass, PickDraw } from './gpu-pick';
import type { PickRegistry } from './pick-registry';

/** How far (CSS px) a mouse may move and still click. More is a drag. */
const CLICK_DRAG_PX = 3;
/** The same for a finger or a pen, which moves a few px during a tap. */
const TOUCH_SLOP_PX = 10;

/** True when the pointer is past the distance a click may move. */
function movedTooFar(e: PointerEvent, from: Vector2): boolean {
	const limit = isCoarsePointer(e.pointerType) ? TOUCH_SLOP_PX : CLICK_DRAG_PX;
	return Math.hypot(e.clientX - from.x, e.clientY - from.y) > limit;
}

/** One resolved point-cloud candidate, comparable to a moon CPU hit. */
interface PointHit {
	body: PositionedBody;
	/** Scene-unit distance from the camera (for depth tie-breaks vs mesh hits). */
	distance: number;
	/** CSS-px distance from the cursor (primary ranking). */
	screenDist: number;
}

/** True when the top-level object that holds `obj` is hidden. A raycast does
 *  not read `visible`, and a body with no place is not there to click. */
function inHiddenRoot(obj: Object3D): boolean {
	let top = obj;
	while (top.parent?.parent) top = top.parent;
	return !top.visible;
}

/** Pointer handlers that tell a click from a drag or a pinch and pick the
 *  topmost body under the cursor. Moons and meshes resolve on the CPU; the
 *  asteroid/spacecraft clouds and the stars resolve on the GPU via
 *  {@link GpuPickPass}. */
export class PointerInteraction {
	private readonly downPos = new Vector2();
	/** Pointers down now, by id. */
	private readonly down = new Set<number>();
	/** The gesture since the first pointer went down is not a click: a second
	 *  pointer joined it, or one moved past the tolerance. */
	private gesture = false;
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
		private readonly pickRegistry: PickRegistry,
		/** The stars as the pick pass draws them; empty while none draw. */
		private readonly getStars: () => PickDraw[],
		/** Takes a star's pick-id; false when it names no star. */
		private readonly onStarPick: (pickId: number) => boolean
	) {}

	attach(): void {
		this.canvas.addEventListener('pointerdown', this.onDown);
		this.canvas.addEventListener('pointermove', this.onMove);
		this.canvas.addEventListener('pointerup', this.onUp);
		this.canvas.addEventListener('pointercancel', this.onCancel);
	}

	detach(): void {
		this.canvas.removeEventListener('pointerdown', this.onDown);
		this.canvas.removeEventListener('pointermove', this.onMove);
		this.canvas.removeEventListener('pointerup', this.onUp);
		this.canvas.removeEventListener('pointercancel', this.onCancel);
	}

	private onDown = (e: PointerEvent): void => {
		// The first pointer starts a gesture, and drops any id whose up never came.
		if (e.isPrimary) {
			this.down.clear();
			this.gesture = false;
			this.downPos.set(e.clientX, e.clientY);
		} else {
			this.gesture = true;
		}
		this.down.add(e.pointerId);
	};

	/** A drag that comes back to where it started is still a drag. */
	private onMove = (e: PointerEvent): void => {
		if (this.gesture || !this.down.has(e.pointerId)) return;
		if (movedTooFar(e, this.downPos)) this.gesture = true;
	};

	private onCancel = (e: PointerEvent): void => {
		this.down.delete(e.pointerId);
		this.gesture = true;
	};

	private onUp = (e: PointerEvent): void => {
		const known = this.down.delete(e.pointerId);
		if (!known || this.gesture || movedTooFar(e, this.downPos)) return;

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

		// Mesh under the cursor — a planet, or a mounted natural-body model (the
		// hidden sphere covers only part of an irregular silhouette, so the model
		// must be hit-testable itself). Only a fallback: a point-cloud body
		// always wins so small dots stay clickable (esp. touch).
		const meshBody = this.resolveMeshHit(
			this.raycaster.intersectObjects<Object3D>([...this.clickables, ...attachedModelRoots])
		)?.body;

		// Moon dots and the planets and host stars of other stars' systems (CPU,
		// a few hundred), and asteroid/spacecraft dots (GPU pick pass). The
		// nearest to the cursor wins, depth breaking ties, so a clicked moon
		// still outranks an asteroid dot drifting behind it.
		const dots: DotPick = {
			pointer: this.pointer,
			camera: this.camera,
			ctx: this.ctx,
			focusTruePos: this.focus.focusTruePos,
			canvasWidth: this.canvas.clientWidth,
			canvasHeight: this.canvas.clientHeight,
			tmpV3: this._tmpV3,
			jd: this.clock.jd,
			pointerType: e.pointerType,
			isVisible: this.isDotVisible
		};
		const moonHit = pickMoonDot(dots);
		const systemHit = pickSystemDot(dots);
		const gpuHit = this.gpuPickCloud(e, rect);
		const pointHit = this.nearer(this.nearer(moonHit, systemHit), gpuHit);

		const bestBody = pointHit?.body ?? meshBody;
		if (bestBody) {
			this.onPick(bestBody);
			return;
		}
		this.pickStar(e, rect, dots);
	};

	/** The stars are behind everything: they pick only where nothing of the
	 *  solar system does, the Sun's and the planets' points included. Then the
	 *  nearest drawn star not hidden behind a body. */
	private pickStar(e: PointerEvent, rect: DOMRect, dots: DotPick): void {
		const stars = this.getStars();
		if (stars.length === 0) return;
		const planet = pickPlanetDot(dots);
		if (planet) {
			this.onPick(planet.body);
			return;
		}
		const candidates = this.gpuPick.pickDraws(
			stars,
			this.camera,
			e.clientX,
			e.clientY,
			rect,
			pickRadiusPx(e.pointerType)
		);
		for (const c of candidates) {
			if (!this.isDotVisible(c.ndcX, c.ndcY, Infinity)) continue;
			if (this.onStarPick(c.pickId)) return;
		}
	}

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
		const jd = this.clock.jd;
		const candidates = this.gpuPick.pick(
			this.getClouds(),
			this.camera,
			e.clientX,
			e.clientY,
			rect,
			pickRadiusPx(e.pointerType)
		);
		for (const c of candidates) {
			const bodyId = this.pickRegistry.resolve(c.pickId);
			if (!bodyId) continue;
			const body = this.ctx.getBody(bodyId);
			if (!body) continue;
			// Settle the row at the current jd, so its place matches the rendered
			// dot and feeds the focus animation.
			const at = this.ctx.place(body, jd);
			if (!at) continue;
			const worldDist = this.worldDistOf(at);
			if (!this.isDotVisible(c.ndcX, c.ndcY, worldDist)) continue; // occluded — try next
			return { body, distance: worldDist, screenDist: c.pixelDist };
		}
		return null;
	}

	/** Scene-unit distance from the camera to a place of the scene. */
	private worldDistOf(at: readonly [number, number, number]): number {
		const [fx, fy, fz] = this.focus.focusTruePos;
		const cam = this.camera.position;
		return Math.hypot(at[0] - fx - cam.x, at[1] - fy - cam.y, at[2] - fz - cam.z);
	}

	/** First raycast hit that resolves to a body. Walks parents so child meshes
	 *  (cloud shells, nomenclature labels, model sub-meshes) resolve to their
	 *  body — model mounts carry theirs in `userData.pickBody`. */
	private resolveMeshHit(
		hits: Intersection[]
	): { body: PositionedBody; distance: number } | undefined {
		for (const hit of hits) {
			if (inHiddenRoot(hit.object)) continue;
			let obj: Object3D | null = hit.object;
			while (obj) {
				const mapped = this.meshToBody.get(obj as Mesh) ?? obj.userData.pickBody;
				if (mapped) return { body: mapped as PositionedBody, distance: hit.distance };
				obj = obj.parent;
			}
		}
		return undefined;
	}

	/** A dot is visible unless a solid mesh, a mounted natural-body model, or
	 *  the focused body's overlay model (which composites over the main scene)
	 *  sits in front of it on its own ray. Non-recursive over clickables: only
	 *  the depth-writing surface spheres occlude, not their transparent
	 *  cloud/atmosphere shells. */
	private isDotVisible = (ndcX: number, ndcY: number, worldDist: number): boolean => {
		if (this.modelPick(ndcX, ndcY)) return false;
		if (this.clickables.length === 0 && attachedModelRoots.size === 0) return true;
		this._tmpPointer.set(ndcX, ndcY);
		this.raycaster.setFromCamera(this._tmpPointer, this.camera);
		const hits = this.raycaster.intersectObjects(this.clickables, false);
		if (attachedModelRoots.size > 0) {
			hits.push(...this.raycaster.intersectObjects<Object3D>([...attachedModelRoots], true));
		}
		let nearest = Infinity;
		for (const h of hits) {
			if (h.distance < nearest && !inHiddenRoot(h.object)) nearest = h.distance;
		}
		return nearest >= worldDist * 0.999;
	};
}
