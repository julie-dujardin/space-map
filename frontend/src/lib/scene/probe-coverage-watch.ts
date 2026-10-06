/**
 * Pauses the sim clock at the edges of the focused probe's coverage and
 * reports it. A probe has no trajectory past its SPICE data, so the edge of a
 * coverage window is a hard wall: the clock stops there, and the probe stays
 * on screen. A hole inside the coverage stops it too.
 */

import { coverageOf, type CoverageWindow } from '$lib/fetch/coverage';
import { OrbitalSource } from '$lib/fetch/position/format';
import type { PositionedBody } from '$lib/types/objects';
import type { SimClock } from '$lib/scene/state/clock.svelte';
import type { NoticeSink } from './notice';

/** Pull the stop inward by this much (JD days, ≈86 ms) so the snap lands
 *  inside the probe's last sub-chunk, not on its half-open upper bound:
 *  `findSubChunkIndex` misses there and the probe has no place at the pause
 *  frame. It is also what lets the strict `<` guard of `SimClock.tick` advance
 *  past the stop on the next Play. */
const STOP_INSET_JD = 1e-6;

/** A probe's `data.name` is `string | null` (rare); fall back to the bare id
 *  so we never render `null` into the notice. */
function displayName(body: PositionedBody): string {
	return body.data.name ?? body.data.id;
}

export class ProbeCoverageWatch {
	private armedProbeId: string | null = null;
	/** Whether the notice is live, so it is dismissed when focus changes or
	 *  jd re-enters coverage. */
	private noticeShown = false;
	/** Coverage windows per probe id. Absent key: not fetched yet. */
	private readonly coverage = new Map<string, CoverageWindow[]>();
	private readonly pending = new Set<string>();

	constructor(
		private readonly clock: SimClock,
		private readonly notices: NoticeSink
	) {}

	/** Windows of `probeId`, fetched and cached on first ask. Until they
	 *  resolve, `sync` finds nothing and stays disarmed. */
	private windowsOf(probeId: string): CoverageWindow[] | undefined {
		const cached = this.coverage.get(probeId);
		if (cached) return cached;
		if (!this.pending.has(probeId)) {
			this.pending.add(probeId);
			coverageOf(probeId)
				.catch((e) => {
					console.warn(`[coverage] ${probeId}: no coverage to arm the clock with:`, e);
					return [];
				})
				.then((windows) => this.coverage.set(probeId, windows))
				.finally(() => this.pending.delete(probeId));
		}
		return undefined;
	}

	/** Per-frame entry point. Cheap when nothing changed. Call before
	 *  {@link SimClock.tick} so stops are armed for the upcoming step. */
	sync(focused: PositionedBody | undefined, jd: number): void {
		const probe = focused?.data.orbitalSource === OrbitalSource.SPICE_PROBE ? focused : undefined;
		// The window the clock is in. Outside every window there is no wall ahead.
		const window = probe && this.windowsOf(probe.data.id)?.find(([s, e]) => jd > s && jd < e);
		if (!probe || !window) {
			this.disarm();
			return;
		}

		if (this.armedProbeId !== probe.data.id) {
			// Focus moved to a different probe: the old probe's edge is irrelevant now.
			this.dismissNotice();
			this.armedProbeId = probe.data.id;
		}

		const forwardJd = window[1] - STOP_INSET_JD;
		const backwardJd = window[0] + STOP_INSET_JD;

		// The user scrubbed back in, or reversed past the edge: the wall message is stale.
		if (this.noticeShown && jd > backwardJd && jd < forwardJd) this.dismissNotice();

		this.clock.setBoundaryStops({
			forwardJd: Number.isFinite(forwardJd) ? forwardJd : null,
			backwardJd: Number.isFinite(backwardJd) ? backwardJd : null,
			onHit: (hitJd) => this.onHit(probe, hitJd, forwardJd)
		});
	}

	private onHit(body: PositionedBody, hitJd: number, forwardJd: number): void {
		this.notices.notify({
			topic: 'coverage-pause',
			name: displayName(body),
			direction: hitJd >= forwardJd ? 'forward' : 'backward',
			jd: hitJd
		});
		this.noticeShown = true;
	}

	private disarm(): void {
		if (this.armedProbeId === null) return;
		this.armedProbeId = null;
		this.dismissNotice();
		this.clock.setBoundaryStops(null);
	}

	private dismissNotice(): void {
		if (!this.noticeShown) return;
		this.notices.dismiss('coverage-pause');
		this.noticeShown = false;
	}
}
