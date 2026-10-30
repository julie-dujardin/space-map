/**
 * The star system of the focused body. Every point of the system draws as an
 * exact star while the focus is in the system, because the float32 place of a
 * row moves in steps when the camera is near it.
 */

import { ExtrasolarStaleError } from '$lib/fetch/extrasolar/files';
import { extrasolarObjectId } from '$lib/fetch/extrasolar/ids';
import { loadSystemPoints, systemRoot } from '$lib/fetch/extrasolar/systems';
import { RetryBackoff } from '$lib/fetch/retry-backoff';
import type { Vec3 } from '$lib/scene/animation/math';
import { ensureExtrasolarBody } from '$lib/scene/setup/extrasolar';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import type { PositionedBody, StarAnchor } from '$lib/types/objects';

export class FocusedStarSystem {
	private root: number | null = null;
	/** The IDs with a point of their own, once the system's rows are in. */
	private ids: readonly number[] = [];
	private near: StarAnchor[] = [];
	private asked = false;
	/** Failed loads wait before they are asked for again. */
	private readonly retries: RetryBackoff<number>;

	constructor(
		private readonly ctx: ContextManager,
		/** Called when a load lands that the next frame should draw. */
		private readonly onChange: () => void
	) {
		this.retries = new RetryBackoff(onChange);
	}

	/** The IDs of the bodies to hold. */
	get points(): readonly number[] {
		return this.ids;
	}

	/** The stars whose records are in, nearest the camera first. */
	get stars(): readonly StarAnchor[] {
		return this.near;
	}

	/** Follow the focus. `camera` is the scene position, barycentre origin. */
	update(focused: PositionedBody | undefined, [cx, cy, cz]: Readonly<Vec3>): void {
		const root = this.rootOf(focused);
		if (root !== this.root) {
			this.root = root;
			this.ids = [];
			this.near = [];
			// A body that went past the LRU loads again on the way back.
			this.asked = false;
		}
		if (root === null) return;
		this.ask(root);
		const distance = ({ scene }: StarAnchor): number =>
			scene ? Math.hypot(scene[0] - cx, scene[1] - cy, scene[2] - cz) : Infinity;
		this.near = this.ids
			.flatMap((id) => this.ctx.getBody(extrasolarObjectId(id))?.extrasolar ?? [])
			.sort((a, b) => distance(a) - distance(b));
	}

	/** The system of a focused star, node, held star or planet. */
	private rootOf(body: PositionedBody | undefined): number | null {
		const host = body?.exoplanet?.host;
		const star = host === undefined ? body : this.ctx.getBody(extrasolarObjectId(host));
		const record = star?.extrasolar?.record;
		return record ? systemRoot(record) : null;
	}

	private ask(root: number): void {
		if (this.asked || this.retries.waiting(root)) return;
		this.asked = true;
		this.load(root).then(
			() => this.retries.clear(root),
			(e) => {
				console.warn(`[systems] the system ${root} did not load:`, e);
				// Files from a newer export: the reload prompt is up, and nothing more loads.
				if (e instanceof ExtrasolarStaleError) return;
				if (root === this.root) this.asked = false;
				this.retries.fail(root);
			}
		);
	}

	/** Each star draws when its record lands. */
	private async load(root: number): Promise<void> {
		const ids = await loadSystemPoints(root);
		if (root !== this.root) return;
		this.ids = ids;
		await Promise.all(
			ids.map(async (id) => {
				await ensureExtrasolarBody(this.ctx, extrasolarObjectId(id));
				this.onChange();
			})
		);
	}
}
