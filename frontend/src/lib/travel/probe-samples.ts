/**
 * A probe's measured positions about its primary, as the kernel takes them.
 *
 * An osculating fit describes a probe for about as long as it was fitted over,
 * which is fine for a cruise across the solar system and useless inside one
 * system: a trip there is priced entirely on how far apart the two ends are,
 * and a body held at a Lagrange point has no conic about its primary at all.
 * Webb's reads as a 126-day ellipse swinging between 0.6 and 1.5 million km,
 * so a search against it offers arcs to distances Webb is never at.
 *
 * So the separation is measured rather than modelled, off the same position
 * stream the renderer draws the probe with. See `EphemerisSamples`.
 */

import type { EphemerisSamples } from '$lib/math/travel';
import type { ProbeStore } from '$lib/fetch/position/probes/store';
import { probeStateKm } from '$lib/fetch/position/probes/propagate';
import { getGmKm3s2 } from '$lib/fetch/systems-global';
import { SECONDS_PER_DAY } from '$lib/time/jd';

/**
 * How far ahead to measure, and how finely.
 *
 * The span covers any grid a same-system search can build: its departure axis
 * is one turn of the satellite and the slowest arc across a primary's sphere is
 * weeks on top of that. Taken as a flat number rather than derived from the
 * bounds, because the bounds are what these are for.
 *
 * Two days is far tighter than the curve needs — the interpolation is cubic and
 * carries the sampled velocities — but a couple of hundred positions costs
 * nothing to read or to copy into the solver.
 */
const SPAN_DAYS = 400;
const STEP_DAYS = 2;

/** How far apart to ask the store to warm. Chunks are half a year, so this
 *  never misses one and never asks for the same one twice. */
const WARM_STEP_DAYS = 60;

/**
 * Where `id` is, measured from `centerId`, over the dates a trip leaving around
 * `fromJd` can reach.
 *
 * Null unless the whole thing can be answered: not a probe, no stream, or the
 * probe goes round something else. A short series is returned where coverage
 * runs out — the kernel falls back to the elements beyond its last date, which
 * is the same answer it would have given without any of this.
 */
export async function probeSamples(
	store: ProbeStore | null | undefined,
	id: string,
	centerId: string,
	fromJd: number
): Promise<EphemerisSamples | null> {
	if (!store || !id.startsWith('probe-')) return null;
	const centerNaifId = Number(centerId.replace('naif-', ''));
	if (!Number.isFinite(centerNaifId)) return null;
	const mu = getGmKm3s2(centerNaifId);
	if (!mu || !(mu > 0)) return null;

	const toJd = fromJd + SPAN_DAYS;
	for (let jd = fromJd; jd < toJd + WARM_STEP_DAYS; jd += WARM_STEP_DAYS) {
		await store.warmAt(Math.min(jd, toJd));
	}

	const jds: number[] = [];
	const r: [number, number, number][] = [];
	const v: [number, number, number][] = [];
	for (let jd = fromJd; jd <= toJd; jd += STEP_DAYS) {
		let located = store.probeWithCenter(id, jd);
		// The store keeps a fixed number of off-clock chunks, so one warmed at the
		// top of this can have been dropped by the time the loop reaches it. Ask
		// again for the date itself before believing the coverage has run out.
		if (!located) {
			await store.warmAt(jd);
			located = store.probeWithCenter(id, jd);
		}
		// Coverage ending is where the series ends — the kernel offers no trip past
		// its last date, which is the honest answer. So is a probe that goes round
		// something else by then: that is not this trip.
		if (!located || located.fitCenterNaifId !== centerNaifId) break;
		const state = probeStateKm(located.probe, jd, mu);
		if (!state) break;
		jds.push(jd);
		r.push(state.position);
		v.push([
			state.velocity[0] / SECONDS_PER_DAY,
			state.velocity[1] / SECONDS_PER_DAY,
			state.velocity[2] / SECONDS_PER_DAY
		]);
	}
	return jds.length > 1 ? { centerId, jds, r, v } : null;
}
