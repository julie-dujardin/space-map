/**
 * Pauses the sim clock at the focused probe's coverage edges. Each frame
 * `sync` arms {@link SimClock.setBoundaryStops} with the focused probe's
 * `(start_jd, end_jd)` from `metadata.position.probe_coverage`; tick clamps
 * jd to the nearest edge in the time-step direction and pauses. A toast
 * fires on hit and auto-dismisses when jd moves back inside coverage or
 * focus changes.
 *
 * Why this matters: heliocentric/hyperbolic probes propagate beyond their
 * SPICE data (writer-side, since `e2fbf2bb`), so `(start_jd, end_jd)` is
 * "everything the writer could produce" — past these edges the probe truly
 * has no position. Stopping there tells the user they hit a data wall, not
 * a fit boundary.
 */

import { toast } from 'svelte-sonner';
import * as m from '$lib/paraglide/messages.js';
import { formatJulianDate } from '$lib/format/date';
import type { ProbeCoverage } from '$lib/fetch/metadata';
import type { PositionedBody } from '$lib/types/objects';
import type { SimClock } from '$lib/scene/state/clock.svelte';

const TOAST_ID_PREFIX = 'coverage-pause:';

/** Pull the stop inward by this much (JD days, ≈86 ms) so the snap lands
 *  inside the probe's last sub-chunk instead of on its half-open `[start, end)`
 *  upper bound. Without this, `findSubChunkIndex(et === subEndEt[last])`
 *  returns -1 and the probe disappears at the exact pause frame — the snap
 *  pause + invisible probe is the bug the user reported. The offset is tiny
 *  relative to any sub-chunk (≥0.5 day for planet zones, 7 days interplanetary),
 *  so the displayed `formatJulianDate(hitJd)` rounds to the same calendar
 *  second as the actual edge.
 *
 *  Anti-rebound falls out of `SimClock.tick`'s strict `this.jd < forwardJd`
 *  check: after the snap, `jd === forwardJd_armed`, so the next tick (after
 *  the user hits Play) fails the strict-less-than guard and advances past.
 */
const STOP_INSET_JD = 1e-6;

/** A probe's `data.name` is `string | null` (rare); fall back to the bare id
 *  so we never render `null` into the toast. */
function displayName(body: PositionedBody): string {
	return body.data.name ?? body.data.id;
}

export class ProbeCoverageWatch {
	private armedProbeId: string | null = null;
	/** Toast id currently showing for the armed probe, or null. Tracked so we
	 *  dismiss the right toast when focus changes / jd re-enters coverage. */
	private activeToastId: string | null = null;

	constructor(
		private readonly clock: SimClock,
		/** Per-probe `(start_jd, end_jd)` from metadata. Empty when the export
		 *  predates the field — the watch becomes a no-op. */
		private readonly coverage: Map<string, ProbeCoverage>
	) {}

	/** Per-frame entry point. Cheap when nothing changed. Call before
	 *  {@link SimClock.tick} so stops are armed for the upcoming step. */
	sync(focused: PositionedBody | undefined, jd: number): void {
		const probeId = focused?.data.id ?? null;
		const cov = probeId !== null ? this.coverage.get(probeId) : undefined;

		if (!focused || !cov) {
			this.disarm();
			return;
		}

		if (this.armedProbeId !== probeId) {
			// Focus moved to a different probe — drop the old toast (the old
			// probe's edge is irrelevant now) and let the new probe arm fresh.
			this.dismissActiveToast();
			this.armedProbeId = probeId;
		}

		const forwardJd = cov.end_jd - STOP_INSET_JD;
		const backwardJd = cov.start_jd + STOP_INSET_JD;

		// Dismiss the active toast once jd is back inside coverage. The user
		// either scrubbed back in or reversed direction past the edge; either
		// way the wall message is stale.
		if (this.activeToastId !== null && jd > backwardJd && jd < forwardJd) {
			this.dismissActiveToast();
		}

		this.clock.setBoundaryStops({
			forwardJd,
			backwardJd,
			onHit: (hitJd) => this.onHit(focused, hitJd, forwardJd)
		});
	}

	private onHit(body: PositionedBody, hitJd: number, forwardJd: number): void {
		const isForward = hitJd >= forwardJd;
		const name = displayName(body);
		const date = formatJulianDate(hitJd);
		const id = `${TOAST_ID_PREFIX}${body.data.id}:${isForward ? 'forward' : 'backward'}`;
		const description = isForward
			? m.coverage_pause_forward({ name, date })
			: m.coverage_pause_backward({ name, date });
		// Forward-then-backward (or vice versa) without transiting through
		// coverage interior — drop the stale toast before showing the new one.
		if (this.activeToastId !== null && this.activeToastId !== id) {
			toast.dismiss(this.activeToastId);
		}
		toast.info(m.coverage_pause_title(), {
			id,
			description,
			duration: Number.POSITIVE_INFINITY
		});
		this.activeToastId = id;
	}

	private disarm(): void {
		if (this.armedProbeId === null && this.activeToastId === null) return;
		this.armedProbeId = null;
		this.dismissActiveToast();
		this.clock.setBoundaryStops(null);
	}

	private dismissActiveToast(): void {
		if (this.activeToastId === null) return;
		toast.dismiss(this.activeToastId);
		this.activeToastId = null;
	}
}
