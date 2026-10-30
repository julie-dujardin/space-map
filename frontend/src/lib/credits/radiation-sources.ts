/**
 * The works behind the radiation, dust and gas figures of a trip and its
 * radiation shield, for the citation line of the route panel.
 *
 * The browser computes these figures from constants, so no fetch brings their
 * sources. The radiation works are a copy of the entries in
 * `constants/radiation/references.py`. Only the terms that a trip uses are
 * here. The /credits page lists the full radiation bibliography. The human
 * response, dust, gas density, hull and shield works have no Python entry,
 * because only the TypeScript uses them.
 *
 * Titles are English in every locale, as are the spacecraft citations.
 */

import { SUN_ID } from '$lib/constants';
import { systemOf } from '$lib/state/nav-end';
import { gasReading } from '$lib/travel/hazard-labels';
import type { Hazard } from '$lib/travel/hazards';
import type { SourceCitation } from '$lib/travel/vehicles';

/** The rate at 1 au. The rate past the heliopause is a multiple of it. */
const CRUISE_DOSE: SourceCitation = {
	title: 'Guo et al. 2021 (The Astronomy and Astrophysics Review 29)',
	url: 'https://doi.org/10.1007/s00159-021-00136-5',
	note: 'cruise dose & solar cycle'
};

const CANCER_RISK: SourceCitation = {
	title: 'ICRP Publication 103 (Annals of the ICRP 37)',
	url: 'https://www.icrp.org/publication.asp?id=ICRP%20Publication%20103',
	note: 'lifetime cancer risk per sievert'
};

/** The terms of the fit inside the heliopause. A trip between two other stars
 *  does not go there, so these terms do not apply to it. */
const HELIOSPHERE_SOURCES: readonly SourceCitation[] = [
	{
		title: 'Roussos et al. 2020 (The Astrophysical Journal 904, 165)',
		url: 'https://doi.org/10.3847/1538-4357/abc346',
		note: 'radial gradient'
	},
	{
		title: 'SIDC/SILSO, Royal Observatory of Belgium: solar cycle minima',
		url: 'https://www.sidc.be/SILSO/solar-cycle-minimum-passed-december-2019',
		note: 'solar cycle epoch'
	}
];

/** Jupiter's belt structure, which is also what the dose profile is shaped on. */
const JOVIAN_BELT_STRUCTURE: SourceCitation = {
	title: 'Roussos & Kollmann 2020 (AGU Geophysical Monograph 259)',
	url: 'https://doi.org/10.48550/arXiv.2006.14682',
	note: 'giant planet belts'
};

/** What a dose in grays is read against. */
const LETHAL_DOSE: SourceCitation = {
	title: 'CDC, Acute Radiation Syndrome: information for clinicians',
	url: 'https://www.cdc.gov/radiation-emergencies/hcp/clinical-guidance/ars.html',
	note: 'lethal dose'
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
	LETHAL_DOSE
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

/** The cosmic-ray dose past the heliopause, on a trip between two systems. */
const INTERSTELLAR_DOSE_SOURCES: readonly SourceCitation[] = [
	{
		title:
			'Mewaldt et al. 2005 (Proceedings of the 29th International Cosmic Ray Conference 2, 101)',
		url: 'https://izw1.caltech.edu/ACE/ASC/DATA/bibliography/ICRC2005/usa-mewaldt-RA-abs1-sh35-oral.pdf',
		note: 'interstellar dose'
	},
	{
		title: 'Corti et al. 2016 (The Astrophysical Journal 829, 8)',
		url: 'https://doi.org/10.3847/0004-637X/829/1/8',
		note: 'local interstellar spectra'
	},
	{
		title: 'Cummings et al. 2016 (The Astrophysical Journal 831, 18)',
		url: 'https://doi.org/10.3847/0004-637X/831/1/18',
		note: 'no gradient past the heliopause'
	}
];

/** The dose per particle against its energy. A fast craft meets the cosmic rays
 *  and the gas at higher energies than a craft at rest. */
const DOSE_COEFFICIENT_SOURCES: readonly SourceCitation[] = [
	{
		title: 'Sato et al. 2009 (Physics in Medicine and Biology 54, 1997)',
		url: 'https://doi.org/10.1088/0031-9155/54/7/009',
		note: 'dose per proton'
	},
	{
		title: 'Sato, Endo & Niita 2010 (Physics in Medicine and Biology 55, 2235)',
		url: 'https://doi.org/10.1088/0031-9155/55/8/008',
		note: 'dose per helium nucleus'
	}
];

/** The density of the gas along a crossing. The dust scales with it. */
const GAS_DENSITY_SOURCES: readonly SourceCitation[] = [
	{
		title: 'Linsky et al. 2022 (The Astronomical Journal 164, 106)',
		url: 'https://doi.org/10.3847/1538-3881/ac816b',
		note: 'gas density within 4 pc'
	},
	{
		title: 'Linsky & Redfield 2025 (The Astrophysical Journal 980, 202)',
		url: 'https://doi.org/10.3847/1538-4357/ada89e',
		note: 'hydrogen columns to nearby stars'
	},
	{
		title: 'Swaczyna et al. 2020 (The Astrophysical Journal 903, 48)',
		url: 'https://doi.org/10.3847/1538-4357/abb80a',
		note: 'neutral hydrogen near the Sun'
	},
	{
		title: 'Slavin & Frisch 2008 (Astronomy & Astrophysics 491, 53)',
		url: 'https://doi.org/10.1051/0004-6361:20078101',
		note: 'gas at the Sun'
	}
];

/** The dose behind the hull per proton of the gas. */
const HULL_SOURCES: readonly SourceCitation[] = [
	{
		title:
			'Cossairt 2014 (Fermilab TM-1834 Rev. 13), Radiation Physics for Personnel and Environmental Protection',
		url: 'https://inspirehep.net/literature/361639',
		note: 'neutron yields'
	},
	{
		title: 'NIST PSTAR: Stopping Power and Range Tables for Protons',
		url: 'https://physics.nist.gov/PhysRefData/Star/Text/PSTAR.html',
		note: 'proton ranges'
	},
	{
		title: 'Agosteo et al. 2007 (Nuclear Instruments and Methods in Physics Research B 265, 581)',
		url: 'https://doi.org/10.1016/j.nimb.2007.09.046',
		note: 'neutron attenuation'
	}
];

/** The SATIF-8 proceedings. Two of its papers are works of the shield. */
const SATIF_8_URL =
	'https://www.oecd-nea.org/upload/docs/application/pdf/2020-01/nsc-doc2010-6.pdf';

/**
 * The shield of a crossing: the ISS dose it aims for, the cosmic rays behind
 * thick water, and the neutrons through iron and concrete at the front. The
 * page in each SATIF-8 url keeps the two papers apart.
 */
const SHIELD_SOURCES: readonly SourceCitation[] = [
	{
		title: 'Berger et al. 2017 (Journal of Space Weather and Space Climate 7, A8)',
		url: 'https://doi.org/10.1051/swsc/2017005',
		note: 'ISS dose 2009–2016'
	},
	{
		title:
			'Laramore et al. 2025 (WRMISS 2025), ISS-RAD Measurements through Solar Cycle 25 Min. to Max.',
		url: 'https://ntrs.nasa.gov/citations/20250008430',
		note: 'ISS dose 2016–2025'
	},
	{
		title:
			"Slaba et al. 2016 (NASA HRP Investigators' Workshop), Benchmark Analysis for Space Radiation Transport Codes in Thick Shielding for GCR Environments",
		url: 'https://ntrs.nasa.gov/citations/20160007694',
		note: 'cosmic rays behind thick shields'
	},
	{
		title:
			'Globus & Strout 2017 (NSS Space Settlement Journal), Orbital Space Settlement Radiation Shielding',
		url: 'https://nss.org/wp-content/uploads/2018/01/NSS-JOURNAL-Orbital-Space-Settlement-Radiation-Shielding.pdf',
		note: 'cosmic rays behind water'
	},
	{
		title: 'Sato 2015 (PLoS ONE 10, e0144679)',
		url: 'https://doi.org/10.1371/journal.pone.0144679',
		note: 'cosmic rays under the atmosphere'
	},
	{
		title: 'Dobynde & Guo 2023 (Research Square preprint), Radiation-Safe Human Bases on the Moon',
		url: 'https://doi.org/10.21203/rs.3.rs-2364937/v1',
		note: 'cosmic rays under lunar soil'
	},
	...HULL_SOURCES,
	{
		title: 'Stevenson, Liu & Thomas 1982 (Health Physics 43, 13)',
		url: 'https://doi.org/10.1097/00004032-198207000-00002',
		note: 'Moyer model'
	},
	{
		title: 'Hirayama 2010 (Proceedings of SATIF-8, OECD NEA, 237)',
		url: `${SATIF_8_URL}#page=237`,
		note: 'neutron attenuation in iron'
	},
	{
		title: 'Teichmann 2010 (Proceedings of SATIF-8, OECD NEA, 45)',
		url: `${SATIF_8_URL}#page=45`,
		note: 'neutron attenuation in concrete'
	}
];

/** The grain sizes and their number per volume, on a trip between two systems. */
const DUST_SOURCES: readonly SourceCitation[] = [
	{
		title: 'Weingartner & Draine 2001 (The Astrophysical Journal 548, 296)',
		url: 'https://doi.org/10.1086/318651',
		note: 'grains below 0.3 µm'
	},
	{
		title: 'Krüger et al. 2015 (The Astrophysical Journal 812, 139)',
		url: 'https://doi.org/10.1088/0004-637X/812/2/139',
		note: 'Ulysses grains, 0.3 to 3 µm'
	},
	{
		title: 'Krüger et al. 2019 (Astronomy & Astrophysics 626, A37)',
		url: 'https://doi.org/10.1051/0004-6361/201834316',
		note: 'inflow speed'
	},
	{
		title: 'Landgraf et al. 2000 (Journal of Geophysical Research: Space Physics 105, 10343)',
		url: 'https://doi.org/10.1029/1999JA900359',
		note: 'grains above 3 µm'
	}
];

/**
 * The works behind the radiation, dust and gas rows of a route and its shield,
 * each work one time. `endIds` are the ids of the two ends of the trip. The fit
 * inside the heliopause applies only when one end is in the solar system. The
 * lethal dose applies to a gas row only when its sentence uses it.
 */
export function radiationSources(
	hazards: readonly Hazard[],
	endIds: readonly string[],
	shielded = false
): SourceCitation[] {
	const heliosphere = endIds.some((id) => systemOf(id) === SUN_ID);
	const earned: SourceCitation[] = [];
	for (const hazard of hazards) {
		if (hazard.kind === 'radiation') {
			earned.push(CRUISE_DOSE);
			if (heliosphere) earned.push(...HELIOSPHERE_SOURCES);
			earned.push(CANCER_RISK);
			if (hazard.shipTime) {
				earned.push(...INTERSTELLAR_DOSE_SOURCES, ...DOSE_COEFFICIENT_SOURCES);
			}
		} else if (hazard.kind === 'dust') {
			earned.push(...DUST_SOURCES, ...GAS_DENSITY_SOURCES);
		} else if (hazard.kind === 'gas') {
			earned.push(...DOSE_COEFFICIENT_SOURCES, ...GAS_DENSITY_SOURCES, ...HULL_SOURCES);
			earned.push(CANCER_RISK);
			if (gasReading(hazard.peak) === 'lethal') earned.push(LETHAL_DOSE);
		} else if (hazard.kind === 'belt-crossing') {
			if (!hazard.unpriced) earned.push(...BELT_DOSE_SOURCES);
			else if (hazard.bodyId) {
				const structure = BELT_STRUCTURE_SOURCES[hazard.bodyId];
				if (structure) earned.push(structure);
			}
		}
	}
	if (shielded) earned.push(...SHIELD_SOURCES);
	// By url, because the route panel keys its list by url.
	const seen = new Set<string>();
	const sources: SourceCitation[] = [];
	for (const source of earned) {
		if (seen.has(source.url)) continue;
		seen.add(source.url);
		sources.push(source);
	}
	return sources;
}
