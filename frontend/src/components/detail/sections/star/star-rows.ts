/**
 * What a star's panel shows, from its records: the stat cards and the
 * sections of rows. Every value comes from one column of the record (or a
 * fixed formula of a few), at the precision of its uncertainty. A value from
 * the literature table names its paper, from the star's object entry.
 */

import * as m from '$lib/paraglide/messages.js';
import { getLocale } from '$lib/paraglide/runtime.js';
import type { CrossId } from '$lib/fetch/extrasolar/container';
import {
	astrometricOrbit,
	distanceParallax,
	type DistanceParallax,
	LITERATURE,
	starDistance,
	type ExtrasolarRecord,
	type StarDistance,
	type TableRow
} from '$lib/fetch/extrasolar/lookup';
import { PC_AU } from '$lib/scene/starfield/tree';
import { starRadiusSolar } from '$lib/scene/starfield/record';
import {
	fixed,
	formatDeclination,
	formatRightAscension,
	plusMinus,
	withBounds,
	withError
} from '$lib/format/star';
import { formatBound, formatPercent, joinParts, sigFigures } from '$lib/format/quantities';
import { ltrIsolate } from '$lib/format/bidi';
import { formatTemperature, formatTemperatureRange } from '$lib/format/temperature';
import { starSourceName } from '$lib/credits/star-sources';
import { catalogueQuantity } from '../planet/planet-rows';
import type { GlobalObjectData } from '$lib/fetch/objects/object-data';
import type { Stat } from '../kit/StatCard.svelte';
import { chooseMetallicity, type MetallicityQuantity } from './metallicity';

export const POINT_SOURCE_SLUG = 'point-source';
/** The source name of a parallax from an orbit solution. */
const ORBIT_PARALLAX_SOURCE = 'gaia-dr3-nss';

/** A class probability under this reads as a bound. */
const SMALLEST_SHARE = 1e-4;
/** Light years in one parsec. */
const PC_LY = PC_AU / 63_241.077;
/** Magnitudes per unit of a flux's relative error. */
const MAG_PER_FLUX = 2.5 / Math.LN10;
/** Gaia's validation trusts the FLAME mass of a giant only in this range, in
 *  solar masses (Creevey et al. 2023, A&A 674, A26, Sect. 8). */
const GIANT_MASS_RANGE: [number, number] = [1, 2];

export interface StarRowEntry {
	label: string;
	value: string;
	/** Where the value leads, off the site. */
	href?: string;
	/** What this particular value is. */
	tooltip?: string;
}

export interface StarSection {
	key: string;
	title: string;
	rows: StarRowEntry[];
}

const CATALOGUES: Record<string, { label: () => string; prefix?: string }> = {
	'gaia/dr3': { label: m.star_xid_gaia_dr3, prefix: 'Gaia DR3' },
	'hip/2007': { label: m.star_xid_hip, prefix: 'HIP' },
	'hd/1949': { label: m.star_xid_hd, prefix: 'HD' },
	'iau/wgsn': { label: m.star_xid_iau }
};

/** The catalogues that join the Point source row hold their ids in its columns.
 *  PASTEL names a star as SIMBAD does, so SIMBAD finds the star by it. */
const JOINED_IDS: [column: string, label: () => string, simbad: boolean][] = [
	['pastel_designation', m.star_xid_pastel, true],
	['apogee_id', m.star_xid_apogee, false],
	['lamost_id', m.star_xid_lamost, false]
];

/** Cross-ids not shown. A SIMBAD oid and a NASA Exoplanet Archive row are
 *  internal keys; a literature key and the other planet catalogues' keys
 *  repeat another id or the name of the star. */
const HIDDEN_CATALOGUES = new Set([
	'simbad/oid',
	'literature/star',
	'nasa-exoplanet-archive/pscomppars',
	'exoplanet-eu/catalog',
	'open-exoplanet-catalogue/systems'
]);

const SIMBAD = 'https://simbad.cds.unistra.fr/simbad/sim-id?Ident=';
/** SIMBAD's object-type prefix, as in "* alf CMa" or "Cl* NGC 188 1": not part
 *  of the name. */
const SIMBAD_TYPE_PREFIX = /^(?:[A-Za-z]*\*+|NAME) /;
/** The links section shows the Wikidata item, from the object entry. */
const LINKED_CATALOGUES = new Set(['wikidata']);

function crossIdRow(x: CrossId): StarRowEntry | null {
	const key = `${x.catalogue}/${x.release}`;
	if (HIDDEN_CATALOGUES.has(key)) return null;
	const catalogue = CATALOGUES[key];
	if (!catalogue) return { label: `${x.catalogue} ${x.release}`, value: x.catalogueId };
	const href = catalogue.prefix
		? `${SIMBAD}${encodeURIComponent(`${catalogue.prefix} ${x.catalogueId}`)}`
		: undefined;
	return { label: catalogue.label(), value: x.catalogueId, href };
}

function joinedIdRow(
	id: string | null | undefined,
	label: () => string,
	simbad: boolean
): StarRowEntry | null {
	if (!id || !simbad) return row(label(), id);
	return row(label(), id.replace(SIMBAD_TYPE_PREFIX, ''), SIMBAD + encodeURIComponent(id));
}

const CLASS_LABELS: Record<string, () => string> = {
	star: m.star_class_star,
	pulsar: m.star_class_pulsar,
	'white dwarf': m.star_class_white_dwarf,
	'brown dwarf': m.exoplanet_class_brown_dwarf
};

/** The class a Metadata row names, in words. */
export function starClassLabel(cls: string | null): string {
	return (cls && CLASS_LABELS[cls]?.()) || (cls ?? '');
}

function units() {
	return {
		mas: m.symbol_milliarcsecond(),
		masPerYear: m.symbol_milliarcsecond_per_year(),
		pc: m.symbol_parsec(),
		kms: m.symbol_kilometre_per_second(),
		dex: m.symbol_dex(),
		perMicron: m.symbol_per_micrometre(),
		solarRadius: m.symbol_solar_radius(),
		solarMass: m.symbol_solar_mass(),
		solarLuminosity: m.symbol_solar_luminosity(),
		gigayear: m.symbol_gigaannum()
	};
}

function magnitudeError(row: TableRow, fluxOverError: string): number | null {
	const foe = row.number(fluxOverError);
	return foe !== null && foe > 0 ? MAG_PER_FLUX / foe : null;
}

/** Rows whose value is there; a null value leaves its row out. */
function rows(entries: (StarRowEntry | null)[]): StarRowEntry[] {
	return entries.filter((entry): entry is StarRowEntry => entry !== null);
}

function row(label: string, value: string | null | undefined, href?: string): StarRowEntry | null {
	return value ? { label, value, href } : null;
}

function measured(
	ps: TableRow,
	label: string,
	name: string,
	error: string | number | null,
	unit = '',
	decimals = 2
): StarRowEntry | null {
	const value = ps.number(name);
	if (value === null) return null;
	const err = typeof error === 'string' ? ps.number(error) : error;
	return { label, value: plusMinus(value, err, unit, decimals) };
}

function bounded(ps: TableRow, label: string, name: string, unit = ''): StarRowEntry | null {
	const value = ps.number(name);
	if (value === null) return null;
	return {
		label,
		value: withBounds(value, ps.number(`${name}_lower`), ps.number(`${name}_upper`), unit)
	};
}

const METALLICITY_LABELS: Record<MetallicityQuantity, () => string> = {
	mh: m.star_row_metallicity,
	feh: m.star_row_metallicity_feh
};

/** The metallicity row and its source row; none where no source has a value. */
function metallicityRows(ps: TableRow, orbit: TableRow | null, dex: string): StarRowEntry[] {
	const chosen = chooseMetallicity(ps, orbit, dex);
	if (chosen === null) return [];
	return [
		{ label: METALLICITY_LABELS[chosen.quantity](), value: chosen.value },
		{ label: m.star_row_metallicity_source(), value: starSourceName(chosen.source) }
	];
}

/** A temperature (K) and its percentiles, in the app's temperature unit. The
 *  bounds go where they round to the value itself. */
function temperatureWithBounds(kelvin: number, low: number | null, high: number | null): string {
	const value = formatTemperature({ value: kelvin, unit: 'kelvin' });
	if (low === null || high === null) return value;
	const lowK = { value: low, unit: 'kelvin' };
	const highK = { value: high, unit: 'kelvin' };
	if (formatTemperature(lowK) === formatTemperature(highK)) return value;
	return ltrIsolate(`${value} (${formatTemperatureRange(lowK, highK)})`);
}

function yesNo(value: boolean | null): string | null {
	return value === null ? null : value ? m.star_flag_yes() : m.star_flag_no();
}

/** Free parameters of a Gaia astrometric solution: the bits set in its code. */
function solutionParameters(code: number): number {
	let n = 0;
	for (let bits = code; bits > 0; bits >>= 1) n += bits & 1;
	return n;
}

function epochLabel(epoch: number): string {
	return `J${Number.isInteger(epoch) ? epoch.toFixed(1) : String(epoch)}`;
}

/** The items that are there, as one list in the reader's language. */
function list(items: (string | null)[]): string | null {
	const present = items.filter((item) => item !== null) as string[];
	if (present.length === 0) return null;
	return new Intl.ListFormat(getLocale(), { type: 'conjunction' }).format(present);
}

function pointSource(record: ExtrasolarRecord): TableRow | null {
	return record.rows.get(POINT_SOURCE_SLUG) ?? null;
}

/** The spectral type, a catalogue code, as an LTR isolate. In RTL text the
 *  punctuation at its ends ("A0m...", "B8Ia:") then stays in place. */
function spectralType(ps: TableRow): string | null {
	const code = ps.text('sp_type');
	return code ? ltrIsolate(code) : null;
}

/** FLAME's run on the GSP-Phot parameters (`''`) or on the GSP-Spec ones
 *  (`'_spec'`), as its column names end. */
type FlameRun = '' | '_spec';

/** Whether FLAME fitted a mass that holds. The age and the stage come from the
 *  same fit, so they stand or fall with it. A giant's first flag digit is 1. */
function flameFitHolds(ps: TableRow, run: FlameRun = ''): boolean {
	const mass = ps.number(`mass_flame${run}`);
	if (mass === null) return false;
	if (ps.text(`flags_flame${run}`)?.[0] !== '1') return true;
	return mass >= GIANT_MASS_RANGE[0] && mass <= GIANT_MASS_RANGE[1];
}

/** FLAME's phase index on the BaSTI tracks (Creevey et al. 2023, Sect. 4.4).
 *  Gaia flags nearly every star at 490 as a giant. */
function evolutionaryStage(index: number): string {
	if (index < 390) return m.star_stage_main_sequence();
	if (index < 420) return m.star_stage_turn_off();
	if (index < 490) return m.star_stage_subgiant();
	return m.star_stage_giant();
}

/** The distance FLAME's luminosity rests on, from the second flag digit:
 *  1 is GSP-Phot's distance, 0 and 2 the parallax of the single-star
 *  solution, which the panel's own parallax is not when an orbit gives it.
 *  The run on GSP-Spec has one digit only. */
function flameDistance(ps: TableRow, run: FlameRun, used: DistanceParallax | null): string | null {
	const digit = ps.text(`flags_flame${run}`)?.[1];
	if (digit === '1') return m.star_row_distance_photometric();
	if (digit !== '0' && digit !== '2') return null;
	return used?.fromOrbit ? m.star_flame_single_star_parallax() : m.star_row_parallax();
}

function flameRows(
	ps: TableRow,
	used: DistanceParallax | null,
	u: ReturnType<typeof units>,
	run: FlameRun
): (StarRowEntry | null)[] {
	const column = (name: string) => `${name}_flame${run}`;
	const fit = flameFitHolds(ps, run);
	const stage = ps.number(column('evolstage'));
	return [
		bounded(ps, m.star_stat_radius(), column('radius'), u.solarRadius),
		bounded(ps, m.star_stat_luminosity(), column('lum'), u.solarLuminosity),
		fit ? bounded(ps, m.star_stat_mass(), column('mass'), u.solarMass) : null,
		fit ? bounded(ps, m.star_row_age(), column('age'), u.gigayear) : null,
		fit && stage !== null ? row(m.star_row_evolutionary_stage(), evolutionaryStage(stage)) : null,
		bounded(ps, m.star_row_gravitational_redshift(), column('gravredshift'), u.kms),
		measured(ps, m.star_row_bolometric_correction(), column('bc'), null),
		row(m.star_row_flame_distance(), flameDistance(ps, run, used))
	];
}

/** Distance group sources as sure as a 5σ parallax: a distance chosen from a
 *  paper, and a 5σ SIMBAD parallax. */
const SURE_SOURCES = new Set([LITERATURE, 'simbad-parallax']);

/** Why a distance is uncertain; undefined for one from a 5σ parallax or a paper. */
function uncertainty(distance: StarDistance | null): string | undefined {
	if (!distance || distance.from === 'parallax' || SURE_SOURCES.has(distance.source ?? '')) {
		return undefined;
	}
	return distance.from === 'suspect parallax'
		? m.star_distance_suspect()
		: m.star_distance_uncertain();
}

/** The measured magnitudes the stat cards can show, the first found, in its own
 *  band: a Hipparcos star has no G of its own. */
const APPARENT_MAGNITUDES: [column: string, band: 'G' | 'V'][] = [
	['phot_g_mean_mag', 'G'],
	['v_mag', 'V'],
	['simbad_g_mag', 'G'],
	['simbad_v_mag', 'V'],
	['host_g_mag', 'G'],
	['host_v_mag', 'V']
];

function apparentMagnitude(ps: TableRow): { value: number; band: 'G' | 'V' } | null {
	for (const [column, band] of APPARENT_MAGNITUDES) {
		const value = ps.number(column);
		if (value !== null) return { value, band };
	}
	return null;
}

/** The stat cards, two to a row: the distance and the temperature (or the
 *  spectral type), both magnitudes, then the radius and the mass (or the
 *  luminosity). A card the record has no value for is left out, and an odd
 *  count loses its last. */
export function starStats(record: ExtrasolarRecord): Stat[][] {
	const ps = pointSource(record);
	if (!ps) return [];
	const out: Stat[] = [];
	const distance = starDistance(ps, astrometricOrbit(record));
	const uncertain = uncertainty(distance);
	if (distance !== null) {
		out.push({
			label: m.star_stat_distance(),
			value: joinParts({ value: sigFigures(distance.pc), unit: m.symbol_parsec() }),
			note: joinParts({ value: sigFigures(distance.pc * PC_LY), unit: m.symbol_light_year() }),
			tooltip: uncertain
		});
	}
	const teff = ps.number('teff_gspphot');
	const spType = spectralType(ps);
	if (teff !== null) {
		out.push({
			label: m.star_stat_temperature(),
			value: formatTemperature({ value: teff, unit: 'kelvin' })
		});
	} else if (spType) {
		out.push({ label: m.star_stat_spectral_type(), value: spType });
	}
	const apparent = apparentMagnitude(ps);
	if (apparent) {
		out.push({
			label: m.star_stat_apparent_magnitude(),
			value: fixed(apparent.value, 2),
			note: apparent.band
		});
	}
	if (apparent && distance !== null) {
		out.push({
			label: m.star_stat_absolute_magnitude(),
			value: fixed(apparent.value - 5 * Math.log10(distance.pc) + 5, 2),
			note: apparent.band,
			tooltip: uncertain
		});
	}
	// The radius the scene draws the star with.
	const radius = starRadiusSolar(ps);
	if (radius !== null) {
		out.push({
			label: m.star_stat_radius(),
			value: joinParts({ value: sigFigures(radius), unit: m.symbol_solar_radius() })
		});
	}
	const mass = flameFitHolds(ps) ? ps.number('mass_flame') : null;
	const luminosity = ps.number('lum_flame');
	if (mass !== null) {
		out.push({
			label: m.star_stat_mass(),
			value: joinParts({ value: sigFigures(mass), unit: m.symbol_solar_mass() })
		});
	} else if (luminosity !== null) {
		out.push({
			label: m.star_stat_luminosity(),
			value: joinParts({ value: sigFigures(luminosity), unit: m.symbol_solar_luminosity() })
		});
	}
	const even = out.length % 2 === 1 && out.length > 1 ? out.slice(0, -1) : out;
	const rowsOfTwo: Stat[][] = [];
	for (let i = 0; i < even.length; i += 2) rowsOfTwo.push(even.slice(i, i + 2));
	return rowsOfTwo;
}

/** The sections of rows, in panel order; an empty section is left out.
 *  `references` are the papers of the object entry. */
export function starSections(
	record: ExtrasolarRecord,
	references?: GlobalObjectData['references']
): StarSection[] {
	const u = units();
	const meta = record.metadata;
	const ps = pointSource(record);
	const sections: StarSection[] = [
		{
			key: 'identifiers',
			title: m.star_section_identifiers(),
			rows: rows([
				...meta.crossIds.filter((x) => !LINKED_CATALOGUES.has(x.catalogue)).map(crossIdRow),
				...JOINED_IDS.map(([column, label, simbad]) =>
					joinedIdRow(ps?.text(column), label, simbad)
				),
				row(m.star_row_space_map_id(), String(record.id))
			])
		}
	];
	if (ps) {
		sections.push(
			...pointSourceSections(ps, astrometricOrbit(record), u, references),
			hostStarSection(ps, u)
		);
	}
	return sections.filter((section) => section.rows.length > 0);
}

/** Significant figures a float32 column holds: 1.4 reads back 1.39999998. */
const FLOAT32_DIGITS = 7;

function float32Value(value: number | null): number | null {
	return value === null ? null : Number(value.toPrecision(FLOAT32_DIGITS));
}

/** A value of an exoplanet catalogue, at the digits it gave. */
function catalogued(
	ps: TableRow,
	label: string,
	name: string,
	unit = '',
	error: string | null = null
): StarRowEntry | null {
	const value = float32Value(ps.number(name));
	if (value === null) return null;
	const err = error === null ? null : float32Value(ps.number(error));
	return { label, value: catalogueQuantity(value, err, err, unit) };
}

/** The star as the exoplanet catalogues give it. */
function hostStarSection(ps: TableRow, u: ReturnType<typeof units>): StarSection {
	const teff = ps.number('host_teff');
	const source = ps.text('host_star_source');
	const spType = ps.text('host_spectral_type');
	const hostRows: (StarRowEntry | null)[] = [
		row(m.star_row_catalogue_name(), ps.text('host_name')),
		catalogued(ps, m.star_row_distance(), 'host_distance', u.pc, 'host_distance_error'),
		teff !== null
			? { label: m.star_row_teff(), value: formatTemperature({ value: teff, unit: 'kelvin' }) }
			: null,
		catalogued(ps, m.exoplanet_radius(), 'host_radius', m.exoplanet_symbol_solar_radius()),
		catalogued(ps, m.exoplanet_mass(), 'host_mass', m.exoplanet_symbol_solar_mass()),
		catalogued(ps, m.exoplanet_row_metallicity(), 'host_metallicity', u.dex),
		catalogued(ps, m.star_row_logg(), 'host_logg'),
		catalogued(ps, m.star_row_age(), 'host_age', m.symbol_gigaannum()),
		catalogued(ps, m.star_band_v(), 'host_v_mag'),
		catalogued(ps, m.star_band_g(), 'host_g_mag'),
		catalogued(ps, m.star_band_k(), 'host_k_mag'),
		row(m.star_stat_spectral_type(), spType && ltrIsolate(spType)),
		row(m.star_row_source(), source && starSourceName(source))
	];
	return { key: 'host-star', title: m.star_section_exoplanet_catalogues(), rows: rows(hostRows) };
}

/** The astrometry source, and the orbit solution where its parallax is used. */
function astrometrySourceName(source: string | null, used: DistanceParallax | null): string | null {
	if (!source) return null;
	if (!used?.fromOrbit) return starSourceName(source);
	return m.star_astrometry_orbit_parallax({
		source: starSourceName(source),
		orbit: starSourceName(ORBIT_PARALLAX_SOURCE)
	});
}

/** A distance with its bounds; with one bound or none, at the precision of a
 *  stat card rather than as an exact value. */
function distanceValue(distance: StarDistance, pc: string): string {
	const { lower, upper } = distance;
	if (lower !== null && upper !== null) return withBounds(distance.pc, lower, upper, pc);
	return joinParts({ value: sigFigures(distance.pc), unit: pc });
}

/** The source of a distance that no parallax gives: each paper that the
 *  object entry cites for it, else the name of its catalogue. */
function distanceSources(
	distance: StarDistance | null,
	references: GlobalObjectData['references']
): (StarRowEntry | null)[] {
	const label = m.star_row_distance_source();
	const papers = distance?.source === LITERATURE ? (references?.distance ?? []) : [];
	if (papers.length > 0) {
		return papers.map((paper) => ({ label, value: paper.short, href: paper.url }));
	}
	return [row(label, distance?.source && starSourceName(distance.source))];
}

function pointSourceSections(
	ps: TableRow,
	orbit: TableRow | null,
	u: ReturnType<typeof units>,
	references: GlobalObjectData['references']
): StarSection[] {
	const ra = ps.number('ra');
	const dec = ps.number('dec');
	const epoch = ps.number('epoch');
	const distance = starDistance(ps, orbit);
	// The parallax behind the distance, else the 5σ parallax the row has.
	const used = distance?.parallax ?? distanceParallax(ps, orbit);
	const position: (StarRowEntry | null)[] = [
		ra !== null && dec !== null
			? {
					label: m.star_row_ra(),
					value: withError(
						formatRightAscension(ra, dec, ps.number('ra_error')),
						ps.number('ra_error'),
						u.mas
					)
				}
			: null,
		dec !== null
			? {
					label: m.star_row_dec(),
					value: withError(
						formatDeclination(dec, ps.number('dec_error')),
						ps.number('dec_error'),
						u.mas
					)
				}
			: null,
		epoch !== null ? { label: m.orbit_epoch(), value: epochLabel(epoch) } : null,
		used
			? { label: m.star_row_parallax(), value: plusMinus(used.parallax, used.error, u.mas, 2) }
			: measured(ps, m.star_row_parallax(), 'parallax', 'parallax_error', u.mas),
		distance !== null
			? {
					label: m.star_row_distance(),
					value: distanceValue(distance, u.pc),
					tooltip: uncertainty(distance)
				}
			: null,
		measured(ps, m.star_row_pm_ra(), 'pmra', 'pmra_error', u.masPerYear),
		measured(ps, m.star_row_pm_dec(), 'pmdec', 'pmdec_error', u.masPerYear),
		measured(ps, m.star_row_radial_velocity(), 'radial_velocity', 'radial_velocity_error', u.kms),
		row(m.star_row_astrometry_source(), astrometrySourceName(ps.text('astrometry_source'), used)),
		...distanceSources(distance, references)
	];

	const g = ps.number('phot_g_mean_mag');
	const bp = ps.number('phot_bp_mean_mag');
	const rp = ps.number('phot_rp_mean_mag');
	// Gaia's own colour only; the tree's estimate from V − I is not a measurement.
	const colour = bp !== null && rp !== null ? bp - rp : null;
	const brightness: (StarRowEntry | null)[] = [
		g !== null
			? {
					label: m.star_band_g(),
					value: plusMinus(g, magnitudeError(ps, 'phot_g_mean_flux_over_error'))
				}
			: null,
		bp !== null
			? {
					label: m.star_band_bp(),
					value: plusMinus(bp, magnitudeError(ps, 'phot_bp_mean_flux_over_error'))
				}
			: null,
		rp !== null
			? {
					label: m.star_band_rp(),
					value: plusMinus(rp, magnitudeError(ps, 'phot_rp_mean_flux_over_error'))
				}
			: null,
		colour !== null ? { label: m.star_row_bp_rp(), value: plusMinus(colour, null, '', 3) } : null,
		measured(ps, m.star_band_grvs(), 'grvs_mag', 'grvs_mag_error'),
		measured(ps, m.star_band_hp(), 'hp_mag', 'hp_mag_error', '', 3),
		measured(ps, m.star_band_v(), 'v_mag', null, '', 2),
		measured(ps, m.star_row_b_v(), 'b_v', 'b_v_error', '', 3),
		measured(ps, m.star_row_v_i(), 'v_i', 'v_i_error', '', 2),
		row(m.star_stat_spectral_type(), spectralType(ps)),
		row(
			m.star_row_variability(),
			ps.text('phot_variable_flag') === 'VARIABLE' ? m.star_variable() : null
		)
	];

	const teff = ps.number('teff_gspphot');
	const parameters: (StarRowEntry | null)[] = [
		teff !== null
			? {
					label: m.star_row_teff(),
					value: temperatureWithBounds(
						teff,
						ps.number('teff_gspphot_lower'),
						ps.number('teff_gspphot_upper')
					)
				}
			: null,
		bounded(ps, m.star_row_logg(), 'logg_gspphot'),
		...metallicityRows(ps, orbit, u.dex),
		bounded(ps, m.star_row_distance_photometric(), 'distance_gspphot', u.pc),
		bounded(ps, m.star_row_radius_photometric(), 'radius_gspphot', u.solarRadius),
		bounded(ps, m.star_row_extinction_a0(), 'azero_gspphot'),
		bounded(ps, m.star_row_extinction_g(), 'ag_gspphot'),
		bounded(ps, m.star_row_reddening(), 'ebpminrp_gspphot'),
		row(m.star_row_model_library(), ps.text('libname_gspphot')),
		measured(ps, m.star_row_line_broadening(), 'vbroad', 'vbroad_error', u.kms)
	];

	const solved = ps.number('astrometric_params_solved');
	const excessNoise = ps.number('astrometric_excess_noise');
	const multiPeak = ps.number('ipd_frac_multi_peak');
	const nonSingle = ps.number('non_single_star');
	const share = (name: string) => {
		const p = ps.number(name);
		if (p === null) return null;
		return p < SMALLEST_SHARE ? formatBound(formatPercent(SMALLEST_SHARE)) : formatPercent(p, 3);
	};
	const candidates = list([
		ps.flag('in_qso_candidates') ? m.star_candidates_quasar() : null,
		ps.flag('in_galaxy_candidates') ? m.star_candidates_galaxy() : null
	]);
	const products = list([
		ps.flag('has_xp_continuous') ? m.star_product_xp_continuous() : null,
		ps.flag('has_xp_sampled') ? m.star_product_xp_sampled() : null,
		ps.flag('has_rvs') ? m.star_product_rvs() : null,
		ps.flag('has_epoch_photometry') ? m.star_product_epoch_photometry() : null,
		ps.flag('has_epoch_rv') ? m.star_product_epoch_rv() : null
	]);
	const number = (name: string, decimals: number) => {
		const value = ps.number(name);
		return value === null ? null : fixed(value, decimals);
	};
	const quality: (StarRowEntry | null)[] = [
		row(m.star_row_ruwe(), number('ruwe', 3)),
		row(m.star_row_fidelity(), number('fidelity_v2', 3)),
		row(m.star_row_norm_dg(), number('norm_dg', 2)),
		solved !== null
			? row(
					m.star_row_solution(),
					m.star_solution_parameters({ count: solutionParameters(solved) })
				)
			: null,
		excessNoise !== null
			? row(m.star_row_excess_noise(), plusMinus(excessNoise, null, u.mas, 3))
			: null,
		row(m.star_row_excess_noise_significance(), number('astrometric_excess_noise_sig', 2)),
		row(m.star_row_visibility_periods(), number('visibility_periods_used', 0)),
		row(m.star_row_multi_peak(), multiPeak === null ? null : formatPercent(multiPeak / 100)),
		row(m.star_row_image_asymmetry(), number('ipd_gof_harmonic_amplitude', 3)),
		row(m.star_row_duplicated(), yesNo(ps.flag('duplicated_source'))),
		row(m.star_row_flux_excess(), number('phot_bp_rp_excess_factor', 3)),
		row(
			m.star_row_wavenumber(),
			ps.number('nu_eff_used_in_astrometry') === null
				? null
				: plusMinus(ps.number('nu_eff_used_in_astrometry')!, null, u.perMicron, 3)
		),
		row(
			m.star_row_pseudocolour(),
			ps.number('pseudocolour') === null
				? null
				: plusMinus(ps.number('pseudocolour')!, null, u.perMicron, 3)
		),
		row(m.star_row_rv_transits(), number('rv_nb_transits', 0)),
		row(m.star_row_rv_signal_to_noise(), number('rv_expected_sig_to_noise', 1)),
		row(m.star_row_non_single(), nonSingle === null ? null : yesNo(nonSingle > 0)),
		row(m.star_row_probability_star(), share('classprob_dsc_combmod_star')),
		row(m.star_row_probability_quasar(), share('classprob_dsc_combmod_quasar')),
		row(m.star_row_probability_galaxy(), share('classprob_dsc_combmod_galaxy')),
		row(m.star_row_candidates(), candidates),
		row(m.star_row_products(), products)
	];

	return [
		{ key: 'position', title: m.star_section_position(), rows: rows(position) },
		{ key: 'brightness', title: m.star_section_brightness(), rows: rows(brightness) },
		{ key: 'physical', title: m.physical_properties(), rows: rows(flameRows(ps, used, u, '')) },
		{
			key: 'physical_spec',
			title: m.star_section_physical_spec(),
			rows: rows(flameRows(ps, used, u, '_spec'))
		},
		{ key: 'parameters', title: m.star_section_parameters(), rows: rows(parameters) },
		{ key: 'quality', title: m.star_section_quality(), rows: rows(quality) }
	];
}
