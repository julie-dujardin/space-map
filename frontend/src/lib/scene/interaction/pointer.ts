import { Raycaster, Vector2, Vector3, type Mesh, type PerspectiveCamera } from 'three';
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

		// Mesh hits first (planets, stars, etc.).
		const hits = this.raycaster.intersectObjects(this.clickables);
		let bestBody: PositionedBody | undefined;
		let bestDist = Infinity;
		if (hits.length > 0) {
			const body = this.meshToBody.get(hits[0].object as Mesh);
			if (body) {
				bestBody = body;
				bestDist = hits[0].distance;
			}
		}

		// Then point-cloud bodies (asteroids, spacecraft, moons-as-dots).
		const pointHit = pickPointCloudBody(
			this.pointer,
			this.camera,
			this.ctx,
			this.focus.focusTruePos,
			this.canvas.clientWidth,
			this.canvas.clientHeight,
			this._tmpV3,
			this.clock.jd,
			e.pointerType
		);
		if (pointHit && pointHit.distance < bestDist) bestBody = pointHit.body;

		if (bestBody) this.onPick(bestBody);
	};
}
