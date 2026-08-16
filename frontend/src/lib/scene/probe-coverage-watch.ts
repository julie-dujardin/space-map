/**
 * Pauses the sim clock at the focused probe's coverage edges, with a toast on
 * hit. Heliocentric/hyperbolic probes propagate beyond their SPICE data, so
 * `(start_jd, end_jd)` is a hard data wall, not a fit boundary — worth
 * stopping at rather than silently extrapolating.
 */

import { toast } from 'svelte-sonner';
import * as m from '$lib/paraglide/messages.js';
import { formatJulianDate } from '$lib/format/date';
import { fetchObjectDetail } from '$lib/fetch/objects/object-data';
import type { ProbeCoverage } from '$lib/fetch/metadata';
import type { PositionedBody } from '$lib/types/objects';
import type { SimClock } from '$lib/scene/state/clock.svelte';

const TOAST_ID_PREFIX = 'coverage-pause:';

/** Pull the stop inward by this much (JD days, ≈86 ms) so the snap lands
 *  inside the probe's last sub-chunk, not on its half-open upper bound —
 *  otherwise `findSubChunkIndex` misses and the probe vanishes at the pause
 *  frame. Also what lets `SimClock.tick`'s strict `<` guard advance past the
 *  stop on the next Play instead of re-triggering it. */
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
