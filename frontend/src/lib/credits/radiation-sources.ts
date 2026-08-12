/**
 * The works behind the trip's radiation figures, for the route panel's
 * citation line.
 *
 * A hand mirror of the entries in `constants/radiation/references.py` keyed by
 * `FIELD_SOURCES` and `BELT_FIELD_SOURCES`, the same way
 * `$lib/math/travel/radiation.ts` mirrors the models themselves — the dose is
 * computed in the browser from constants, so no fetch carries its provenance
 * along. Only the terms a trip actually evaluates are here: the planetocentric
 * ones (atmospheric column, geomagnetic cutoff) are skipped in a non-solar
 * frame, so they earn no credit on this surface. The /credits page lists the
 * whole radiation bibliography.
 *
 * The two human-response works have no Python entry to mirror: that package
 * describes how much radiation a *place* delivers, and what it does to a body
 * lives only in the TypeScript.
 *
 * Titles are English in every locale, as the spacecraft citations beside them
 * are.
 */

import type { Hazard } from '$lib/travel/hazards';
import type { SourceCitation } from '$lib/travel/vehicles';

const CRUISE_SOURCES: readonly SourceCitation[] = [
	{
		title: 'Guo et al. 2021 (The Astronomy and Astrophysics Review 29)',
		url: 'https://doi.org/10.1007/s00159-021-00136-5',
		note: 'cruise dose & solar cycle'
	},
	{
		title: 'Roussos et al. 2020 (The Astrophysical Journal 904, 165)',
		url: 'https://doi.org/10.3847/1538-4357/abc346',
		note: 'radial gradient'
	},
	{
		title: 'SIDC/SILSO, Royal Observatory of Belgium: solar cycle minima',
		url: 'https://www.sidc.be/SILSO/solar-cycle-minimum-passed-december-2019',
		note: 'solar cycle epoch'
	},
	{
		title: 'ICRP Publication 103 (Annals of the ICRP 37)',
		url: 'https://www.icrp.org/publication.asp?id=ICRP%20Publication%20103',
		note: 'lifetime cancer risk per sievert'
	}
];

/** Jupiter's belt structure, which is also what the dose profile is shaped on. */
const JOVIAN_BELT_STRUCTURE: SourceCitation = {
	title: 'Roussos & Kollmann 2020 (AGU Geophysical Monograph 259)',
	url: 'https://doi.org/10.48550/arXiv.2006.14682',
	note: 'giant planet belts'
};

/** Behind a belt dose in grays — the profile, the shielding curve, and what
 *  the number is read against. Jupiter is the only body that reaches these. */
const BELT_DOSE_SOURCES: readonly SourceCitation[] = [
	{
		title: 'Miller, Kaufman & Maillie 1976 (Life Sciences and Space Research 14)',
		url: 'https://pubmed.ncbi.nlm.nih.gov/12678105/',
		note: 'Pioneer Jupiter flyby doses'
	},
	JOVIAN_BELT_STRUCTURE,
	{
		title:
			'Johnson, Carlson, Cooper et al. 2004, Radiation Effects on the Surfaces of the Galilean Satellites',
		url: 'https://lasp.colorado.edu/mop/files/2015/08/jupiter_ch20-1.pdf',
		note: 'Galilean surface fluxes'
	},
	{
		title: 'Europa Lander Study 2016 Report (NASA/JPL, Science Definition Team)',
		url: 'https://europa.nasa.gov/resources/58/europa-lander-study-2016-report/',
		note: 'shielding curve'
	},
	{
		title: 'CDC, Acute Radiation Syndrome: information for clinicians',
		url: 'https://www.cdc.gov/radiation-emergencies/hcp/clinical-guidance/ars.html',
		note: 'lethal dose'
	}
];

/**
 * What establishes a belt is there at all, for the passes carrying no figure.
 * Earth's are not here: the row makes no claim a textbook does not.
 */
const BELT_STRUCTURE_SOURCES: Record<string, SourceCitation> = {
	'naif-699': JOVIAN_BELT_STRUCTURE,
	'naif-799': {
		title: 'Garrett et al. 2015 (JPL Publication 15-1), Uranus Radiation Model',
		url: 'https://ntrs.nasa.gov/citations/20160009378',
		note: 'Uranus belt model'
	},
	'naif-899': {
		title: 'Garrett et al. 2017 (JPL Publication 17-3), Neptune Radiation Model',
		url: 'https://ntrs.nasa.gov/citations/20170006886',
		note: 'Neptune belt model'
	}
};

/** The works behind whichever radiation rows a route is showing, once each. */
export function radiationSources(hazards: readonly Hazard[]): SourceCitation[] {
	const earned: SourceCitation[] = [];
	for (const hazard of hazards) {
		if (hazard.kind === 'radiation') {
			earned.push(...CRUISE_SOURCES);
		} else if (hazard.kind === 'belt-crossing') {
			if (!hazard.unpriced) earned.push(...BELT_DOSE_SOURCES);
			else if (hazard.bodyId) {
				const structure = BELT_STRUCTURE_SOURCES[hazard.bodyId];
				if (structure) earned.push(structure);
			}
		}
	}
	const seen = new Set<string>();
	const sources: SourceCitation[] = [];
	for (const source of earned) {
		if (seen.has(source.url)) continue;
		seen.add(source.url);
		sources.push(source);
	}
	return sources;
}
