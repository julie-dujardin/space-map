/**
 * Two skies as one: a fine source that needs time, over a coarse one that is
 * at hand. A chart gets the coarse picture when the fine one is slow, and is
 * told when its own fine picture is in. A fine source that fails is asked
 * again after a wait.
 */

import { RetryBackoff } from '$lib/fetch/retry-backoff';
import type { ChartFrame } from './frame';
import type { ChartSky, Pixels, SkySource } from './sky';

/** The fine picture gets this long before the coarse one is painted. */
const GRACE_MS = 250;

const SLOW = Symbol('slow');
const FINE = 'fine';

/**
 * What the last paint of a frame gave. `interim`: the coarse sky or none,
 * with the fine one still on its way. `below`: the same, with no fine one to
 * come.
 */
type Shown = 'fine' | 'interim' | 'below';

export class LayeredSky implements ChartSky {
	private readonly listeners = new Map<ChartFrame, Set<() => void>>();
	private fine: Promise<SkySource | null> | null = null;
	private coarse: SkySource | null = null;
	private unsubscribe = (): void => {};
	private readonly shown = new WeakMap<ChartFrame, Shown>();
	/** Fine pictures that came in after the coarse one was painted. */
	private readonly late = new WeakMap<ChartFrame, Pixels>();
	/** One failure for all the paints that an outage fails. */
	private readonly retry = new RetryBackoff<typeof FINE>(() => this.tellBelow());

	/** @param openFine Makes the fine source at the first paint. Null: there is none. */
	constructor(private readonly openFine: () => Promise<SkySource | null>) {}

	/** The coarse source, or null while there is none. */
	setCoarse(source: SkySource | null): void {
		this.unsubscribe();
		this.coarse = source;
		this.unsubscribe = source?.onChange(() => this.tellBelow()) ?? (() => {});
		this.tellBelow();
	}

	async paint(
		frame: ChartFrame,
		width: number,
		height: number,
		signal?: AbortSignal
	): Promise<Pixels | null> {
		const kept = this.late.get(frame);
		this.late.delete(frame);
		if (kept?.width === width && kept.height === height) return kept;
		const below = async (): Promise<Pixels | null> =>
			(await this.coarse?.paint(frame, width, height, signal)) ?? null;
		if (this.retry.waiting(FINE)) {
			this.shown.set(frame, 'below');
			return below();
		}
		const fine = this.source().then(async (source) => {
			if (!source) return null;
			try {
				const pixels = await source.paint(frame, width, height, signal);
				if (pixels) {
					this.retry.clear(FINE);
					this.shown.set(frame, 'fine');
				}
				return pixels;
			} catch (e) {
				if (signal?.aborted) return null;
				console.warn('[star-chart] no sky from the tiles:', e);
				this.failed();
				return null;
			}
		});
		const orBelow = (pixels: Pixels | null): Promise<Pixels | null> | Pixels | null => {
			if (pixels || signal?.aborted) return pixels;
			this.shown.set(frame, 'below');
			return below();
		};
		// A chart that shows the fine sky does not go back to the coarse one.
		if (this.shown.get(frame) === 'fine') return orBelow(await fine);
		let timer: ReturnType<typeof setTimeout> | undefined;
		const first = await Promise.race([
			fine,
			new Promise<typeof SLOW>((resolve) => (timer = setTimeout(() => resolve(SLOW), GRACE_MS)))
		]);
		clearTimeout(timer);
		if (first !== SLOW) return orBelow(first);
		this.shown.set(frame, 'interim');
		const coarse = await below();
		// No picture to show meanwhile: one paint, of the fine sky.
		if (!coarse) return orBelow(await fine);
		void fine.then((pixels) => {
			if (signal?.aborted) return;
			if (!pixels) {
				this.shown.set(frame, 'below');
				return;
			}
			this.late.set(frame, pixels);
			this.tell(frame);
		});
		return coarse;
	}

	watch(frame: ChartFrame, listener: () => void): () => void {
		const told = this.listeners.get(frame) ?? new Set();
		this.listeners.set(frame, told);
		told.add(listener);
		return () => {
			told.delete(listener);
			if (told.size === 0) this.listeners.delete(frame);
		};
	}

	private source(): Promise<SkySource | null> {
		this.fine ??= this.openFine().catch((e: unknown) => {
			console.warn('[star-chart] no tile sky:', e);
			this.fine = null;
			this.failed();
			return null;
		});
		return this.fine;
	}

	private failed(): void {
		if (!this.retry.waiting(FINE)) this.retry.fail(FINE);
	}

	private tell(frame: ChartFrame): void {
		for (const listener of [...(this.listeners.get(frame) ?? [])]) listener();
	}

	/** A new coarse sky, or the fine one may be back: for the charts that
	 *  wait for no fine picture. A repaint of the others ends their download. */
	private tellBelow(): void {
		for (const frame of [...this.listeners.keys()]) {
			if (this.shown.get(frame) === 'below') this.tell(frame);
		}
	}
}
