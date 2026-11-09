/**
 * Who to credit for a body's mass, by the export's `mass_source`. Shared by
 * the detail sidebar, which shows the mass of one body, and the Planets page's
 * mass chart, which draws the masses of the planets.
 */
import * as m from '$lib/paraglide/messages.js';
import type { BodyMassFields } from '$lib/fetch/objects/object-data';
import { orientationCredits } from './orientation-sources';
import { catalogueCredit, type SizeCredit } from './size-sources';

/** The credit of a body's mass, null with no mass or with nobody to credit. A
 *  kernel GM is NAIF's, a paper's GM the paper's, and an estimate the export's
 *  own. `page` is the body's own Johnston entry, where the bundle has one. */
export function massCredit(body: BodyMassFields, page?: string): SizeCredit | null {
	const source = body.mass_source;
	if (body.mass_kg == null || !source || source === 'estimate') return null;
	const reference = body.mass_reference;
	if (source === 'literature')
		return typeof reference === 'object'
			? {
					key: reference.url,
					label: reference.title,
					url: reference.url,
					note: m.property_name_mass(),
					paper: true
				}
			: null;
	const note =
		typeof reference === 'string'
			? m.source_mass_reference_role({ reference })
			: m.property_name_mass();
	if (source === 'pck') {
		const naif = orientationCredits('pck').find((credit) => credit.key === 'naif');
		return naif ? { key: naif.key, label: naif.short, url: naif.url, note } : null;
	}
	return catalogueCredit(source, note, page);
}

/** The credits of the masses a chart draws, one per catalogue. */
export function massCredits(bodies: readonly BodyMassFields[]): SizeCredit[] {
	const byKey = new Map<string, SizeCredit>();
	for (const body of bodies) {
		const credit = massCredit(body);
		if (credit && !byKey.has(credit.key)) byKey.set(credit.key, credit);
	}
	return [...byKey.values()];
}
