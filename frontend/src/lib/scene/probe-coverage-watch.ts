/**
 * Pauses the sim clock at the focused probe's coverage edges and tells the
 * host when it does. Heliocentric/hyperbolic probes propagate beyond their
 * SPICE data, so `(start_jd, end_jd)` is a hard data wall, not a fit boundary
 * — worth stopping at rather than silently extrapolating.
 */

import { host } from '$lib/host';
import { fetchObjectDetail } from '$lib/fetch/objects/object-data';
import type { ProbeCoverage } from '$lib/fetch/metadata';
import type { PositionedBody } from '$lib/types/objects';
import type { SimClock } from '$lib/scene/state/clock.svelte';

/** Pull the stop inward by this much (JD days, ≈86 ms) so the snap lands
 *  inside the probe's last sub-chunk, not on its half-open upper bound —
 *  otherwise `findSubChunkIndex` misses and the probe vanishes at the pause
 *  frame. Also what lets `SimClock.tick`'s strict `<` guard advance past the
 *  stop on the next Play instead of re-triggering it. */
const STOP_INSET_JD = 1e-6;

/** A probe's `data.name` is `string | null` (rare); fall back to the bare id
 *  so we never render `null` into the notice. */
function displayName(body: PositionedBody): string {
	return body.data.name ?? body.data.id;
}

export class ProbeCoverageWatch {
	private armedProbeId: string | null = null;
	/** Whether the host is showing our notice, so it is dismissed when focus
	 *  changes or jd re-enters coverage. */
	private noticeShown = false;
	/** Resolved coverage per probe id; `null` once we know a probe has none
	 *  (legacy export). Absent key = not fetched yet. */
	private readonly coverage = new Map<string, ProbeCoverage | null>();
	private readonly pending = new Set<string>();

	constructor(private readonly clock: SimClock) {}

	/** Coverage for `probeId`, fetched-and-cached on first ask. Until it
	 *  resolves, `sync` finds nothing and stays disarmed. */
	private coverageFor(probeId: string): ProbeCoverage | undefined {
		const cached = this.coverage.get(probeId);
		if (cached !== undefined) return cached ?? undefined;
		if (!this.pending.has(probeId)) {
			this.pending.add(probeId);
			fetchObjectDetail(probeId, false)
				.then((d) => this.coverage.set(probeId, d.global?.coverage ?? null))
				.catch(() => this.coverage.set(probeId, null))
				.finally(() => this.pending.delete(probeId));
		}
		return undefined;
	}

	/** Per-frame entry point. Cheap when nothing changed. Call before
	 *  {@link SimClock.tick} so stops are armed for the upcoming step. */
	sync(focused: PositionedBody | undefined, jd: number): void {
		const probeId = focused?.data.id ?? null;
		const cov = probeId !== null ? this.coverageFor(probeId) : undefined;

		if (!focused || !cov) {
			this.disarm();
			return;
		}

		if (this.armedProbeId !== probeId) {
			// Focus moved to a different probe — drop the old notice (the old
			// probe's edge is irrelevant now) and let the new probe arm fresh.
			this.dismissNotice();
			this.armedProbeId = probeId;
		}

		const forwardJd = cov.end_jd - STOP_INSET_JD;
		const backwardJd = cov.start_jd + STOP_INSET_JD;

		// Dismiss the notice once jd is back inside coverage. The user either
		// scrubbed back in or reversed direction past the edge; either way the
		// wall message is stale.
		if (this.noticeShown && jd > backwardJd && jd < forwardJd) {
			this.dismissNotice();
		}

		this.clock.setBoundaryStops({
			forwardJd,
			backwardJd,
			onHit: (hitJd) => this.onHit(focused, hitJd, forwardJd)
		});
	}

	private onHit(body: PositionedBody, hitJd: number, forwardJd: number): void {
		host().notify({
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
		host().dismiss('coverage-pause');
		this.noticeShown = false;
	}
}
