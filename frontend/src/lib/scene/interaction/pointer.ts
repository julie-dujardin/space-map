import {
	Raycaster,
	Vector2,
	Vector3,
	type Intersection,
	type Mesh,
	type Object3D,
	type PerspectiveCamera
} from 'three';
import type { PositionedBody } from '$lib/types/objects';
import type { FocusState } from '$lib/scene/animation/focus';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import type { SimClock } from '$lib/scene/state/clock.svelte';
import { pickPointCloudBody } from './picking';

const CLICK_DRAG_PX2 = 9; // 3px move tolerance — anything larger reads as a drag, not a click.

/**
 * Pointer-down/up handlers that distinguish a click from a drag and pick the
 * topmost body under the cursor (mesh hits first, then point-cloud bodies).
 * Stateless across instances — `attach` returns a cleanup function.
 */
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
		private readonly onPick: (body: PositionedBody) => void
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
		this.raycaster.setFromCamera(this.pointer, this.camera);

		// Mesh under the cursor — the planet you clicked. Only a fallback: a
		// point-cloud body always wins so small dots stay clickable (esp. touch).
		const meshBody = this.resolveMeshHit(this.raycaster.intersectObjects(this.clickables))?.body;

		// Point-cloud bodies (asteroids, spacecraft, moons-as-dots). isDotVisible
		// skips dots hidden behind a planet, so the nearest *visible* dot wins.
		const pointHit = pickPointCloudBody(
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

		const bestBody = pointHit?.body ?? meshBody;
		if (bestBody) this.onPick(bestBody);
	};

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

	/** A dot is visible unless a solid mesh sits in front of it on its own ray.
	 *  Non-recursive: only the depth-writing surface spheres occlude, not their
	 *  transparent cloud/atmosphere shells. */
	private isDotVisible = (ndcX: number, ndcY: number, worldDist: number): boolean => {
		if (this.clickables.length === 0) return true;
		this._tmpPointer.set(ndcX, ndcY);
		this.raycaster.setFromCamera(this._tmpPointer, this.camera);
		const hits = this.raycaster.intersectObjects(this.clickables, false);
		return hits.length === 0 || hits[0].distance >= worldDist * 0.999;
	};
}
