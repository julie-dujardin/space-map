/** When is a body observable? Probes use their `coverage` envelope; Earth sats
 *  use SATCAT launch/decay dates. Returns null for other kinds. */

import { fetchObjectDetail } from '$lib/fetch/objects/object-data';
import { dateToJD } from '$lib/format/date';

export interface CoverageWindow {
	startJd?: number;
	endJd?: number;
}

export async function coverageWindowFor(id: string): Promise<CoverageWindow | null> {
	if (id.startsWith('probe-')) {
		const detail = await fetchObjectDetail(id, false);
		const c = detail.global?.coverage;
		return c ? { startJd: c.start_jd, endJd: c.end_jd } : null;
	}
	if (id.startsWith('norad_satcat-')) {
		const detail = await fetchObjectDetail(id, false);
		const ct = detail.global?.celestrak;
		if (!ct) return null;
		const startJd = ct.launch_date ? dateToJD(new Date(`${ct.launch_date}T00:00:00Z`)) : undefined;
		const endJd = ct.decay_date ? dateToJD(new Date(`${ct.decay_date}T00:00:00Z`)) : undefined;
		return startJd === undefined && endJd === undefined ? null : { startJd, endJd };
	}
	return null;
}

/** Boundary JD to snap to if `jd` is outside the window, else null. */
export function snapJdIntoWindow(jd: number, window: CoverageWindow): number | null {
	if (window.endJd !== undefined && jd > window.endJd) return window.endJd;
	if (window.startJd !== undefined && jd < window.startJd) return window.startJd;
	return null;
}
