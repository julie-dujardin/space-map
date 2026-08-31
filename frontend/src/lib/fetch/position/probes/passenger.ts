/**
 * Find out whether a craft is riding another one, and over what window —
 * Huygens is wherever Cassini is until 2004-12-25, Ingenuity is wherever
 * Perseverance is until it is set down.
 *
 * A passenger has no record in any chunk binary (the archives publish no SPK
 * for hardware that isn't flying separately yet), so nothing would put it in
 * the scene. The export marks it with `coverage.position_from`; handing that
 * to {@link ProbeStore.registerCarried} makes the store emit it off the
 * carrier's record and answer every later lookup about it from there, so it
 * is built by the same path as any other probe.
 */

import type { CarriedFrom } from '$lib/fetch/metadata';
import { fetchObjectDetail } from '$lib/fetch/objects/object-data';
import type { Ride } from '$lib/fetch/position/probes/store';

export interface PassengerGraft {
	/** Object id of the passenger, e.g. `probe-89915392`. */
	id: string;
	carriedFrom: CarriedFrom;
	/** Display name of the carrier, for the credit line under the scene label.
	 *  Taken from the bundle rather than the carrier's scene body — a craft
	 *  focused from a cold URL is streamed in on its own, without it. */
	carrierName?: string;
}

/**
 * The ride `targetId` is on, or undefined when it flies under its own power.
 * The bundle is the one ProbeCoverageWatch already reads for the focused
 * probe, and bundles are LRU-cached by URL, so this costs nothing beyond the
 * first focus.
 */
export async function passengerFor(
	targetId: string | null | undefined
): Promise<PassengerGraft | undefined> {
	if (!targetId?.startsWith('probe-')) return undefined;
	try {
		const global = (await fetchObjectDetail(targetId, false)).global;
		const carriedFrom = global?.coverage?.position_from;
		return carriedFrom
			? { id: targetId, carriedFrom, carrierName: global?.carried_by?.name }
			: undefined;
	} catch {
		return undefined;
	}
}

/** Which craft of each carried pair the renderer draws, and what it captions. */
export interface RideMarkers {
	/** Craft to keep off screen: the half of a pair whose marker would sit on
	 *  top of the other's. */
	hidden: Set<string>;
	/** Passenger id → carrier name, for the credit under its label. */
	credits: Map<string, string>;
}

/**
 * One marker per carried pair: the focused craft of the two, else the carrier,
 * which is the one with a record of its own. The pair is far under a pixel
 * apart, so a second marker there is unreadable rather than informative.
 *
 * The credit is written only under a passenger that is both drawn and still
 * bolted on. Through the handover it has already let go — only the archive's
 * grid still points at the carrier, and that is not something to caption.
 *
 * `sceneName` names a craft the way its own label does, which is the name the
 * credit should repeat; the bundle's spelling ("Cassini Orbiter" against the
 * label's "Cassini") stands in only for a carrier that isn't in the scene.
 */
export function planRideMarkers(
	rides: Iterable<Ride>,
	focusedId: string | undefined,
	sceneName: (id: string) => string | null | undefined
): RideMarkers {
	const hidden = new Set<string>();
	const credits = new Map<string, string>();
	for (const ride of rides) {
		const passengerShown = focusedId === ride.passengerId;
		hidden.add(passengerShown ? ride.carrierId : ride.passengerId);
		if (!passengerShown || !ride.attached) continue;
		const carrier = sceneName(ride.carrierId) ?? ride.carrierName;
		if (carrier) credits.set(ride.passengerId, carrier);
	}
	return { hidden, credits };
}
