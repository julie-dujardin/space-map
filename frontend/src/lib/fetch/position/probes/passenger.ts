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

export interface PassengerGraft {
	/** Object id of the passenger, e.g. `probe-89915392`. */
	id: string;
	carriedFrom: CarriedFrom;
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
		const carriedFrom = (await fetchObjectDetail(targetId, false)).global?.coverage?.position_from;
		return carriedFrom ? { id: targetId, carriedFrom } : undefined;
	} catch {
		return undefined;
	}
}
