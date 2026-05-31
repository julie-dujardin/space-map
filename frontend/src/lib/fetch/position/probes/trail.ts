/**
 * Back-populate a probe trail buffer by walking jd backwards from `centerJd`,
 * sampling `probePositionScene` at each `stepDays` increment. Samples live in
 * the probe's fit-center-relative scene frame; the renderer adds the current
 * parent position at draw time.
 *
 * Skips past samples whose fit center disagrees with `currentParentKey` —
 * cross-zone transitions move the probe under a new fit center, and mixing
 * frames inside one buffer warps the trail. Called from `processProbes` on
 * chunk load (cold-start back-fill) and from `updatePositions` when the live
 * parent flips mid-play (cruise → captured orbit).
 */

import { resolvePrimaryOverride } from '$lib/fetch/position/probes/primary';
import { probePositionScene } from '$lib/fetch/position/probes/propagate';
import { getGmKm3s2 } from '$lib/fetch/systems-global';
import type { ChebyshevStore } from '$lib/fetch/position/chebyshev/store';
import type { ProbeStore } from '$lib/fetch/position/probes/store';
import type { TrailBuffer } from '$lib/fetch/position/trail-buffer';

export function populateProbeTrailBuffer(
	buf: TrailBuffer,
	probeStore: ProbeStore,
	cheb: ChebyshevStore | null,
	probeId: string,
	currentParentKey: string,
	centerJd: number,
	isPreferred?: (fitCenterNaif: number) => boolean
): void {
	for (let k = buf.capacity - 1; k >= 0; k--) {
		const t = centerJd - k * buf.stepDays;
		const located = probeStore.probeWithCenter(probeId, t, isPreferred);
		if (!located) continue;
		const pastZoneKey = `naif-${located.fitCenterNaifId}`;
		const pastOverride = resolvePrimaryOverride(located.probe, t, pastZoneKey, cheb);
		const pastPrimaryKey = pastOverride ? pastOverride.id : pastZoneKey;
		if (pastPrimaryKey !== currentParentKey) continue;
		const pastPrimaryNaif = pastOverride ? pastOverride.naifId : located.fitCenterNaifId;
		const pastMu = pastPrimaryNaif === undefined ? 0 : (getGmKm3s2(pastPrimaryNaif) ?? 0);
		const p = probePositionScene(located.probe, t, pastMu);
		if (p) buf.append(t, p[0], p[1], p[2]);
	}
}
