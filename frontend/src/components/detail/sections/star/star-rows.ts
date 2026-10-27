/** A star's most useful values, grouped by meaning. */

import * as m from '$lib/paraglide/messages.js';
import type { CrossId } from '$lib/fetch/extrasolar/container';
import {
	astrometricOrbit,
	distanceParallax,
	LITERATURE,
	starDistance,
	type ExtrasolarRecord,
	type StarDistance,
	type TableRow
} from '$lib/fetch/extrasolar/lookup';
import { PC_AU } from '$lib/scene/starfield/tree';
import {
	formatDeclination,
	formatRightAscension,
	plusMinus,
	withBounds,
	withError
} from '$lib/format/star';
import {
	formatCatalogueQuantity,
	formatMeasuredQuantity,
	formatUnit,
	joinParts,
	sigFigures
} from '$lib/format/quantities';
import { ltrIsolate } from '$lib/format/bidi';
import { formatTemperature, formatTemperatureRange } from '$lib/format/temperature';
import { SOLAR_RADIUS_KM } from '$lib/math/units';
import type { Stat } from '../kit/StatCard.svelte';
import { chooseMetallicity, type MetallicityQuantity } from './metallicity';

export const POINT_SOURCE_SLUG = 'point-source';

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

/** Catalogue identifiers shown with the object's other links. */
export function starIdentifiers(record: ExtrasolarRecord): StarRowEntry[] {
	const ps = pointSource(record);
	return rows([
		...record.metadata.crossIds.filter((x) => !LINKED_CATALOGUES.has(x.catalogue)).map(crossIdRow),
		...JOINED_IDS.map(([column, label, simbad]) => joinedIdRow(ps?.text(column), label, simbad))
	]);
}

/** Names from the planet catalogues belong with the object's other names. */
export function starAliases(record: ExtrasolarRecord): string[] {
	const name = pointSource(record)?.text('host_name');
	return name && name !== record.metadata.name ? [name] : [];
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
		ly: m.symbol_light_year(),
		kms: m.symbol_kilometre_per_second(),
		dex: m.symbol_dex(),
		km: formatUnit('kilometre', true),
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

function bounded(
	ps: TableRow,
	label: string,
	name: string,
	unit = '',
	scale = 1
): StarRowEntry | null {
	const value = ps.number(name);
	if (value === null) return null;
	const lower = ps.number(`${name}_lower`);
	const upper = ps.number(`${name}_upper`);
	if (scale === 1) return { label, value: withBounds(value, lower, upper, unit) };
	return {
		label,
		value:
			lower === null || upper === null
				? joinParts({ value: sigFigures(value * scale), unit })
				: withBounds(value * scale, lower * scale, upper * scale, unit, true)
	};
}

const METALLICITY_LABELS: Record<MetallicityQuantity, () => string> = {
	mh: m.star_row_metallicity,
	feh: m.star_row_metallicity_feh
};

/** The preferred metallicity row. */
function metallicityRows(ps: TableRow, orbit: TableRow | null, dex: string): StarRowEntry[] {
	const chosen = chooseMetallicity(ps, orbit, dex);
	if (chosen === null) return [];
	return [{ label: METALLICITY_LABELS[chosen.quantity](), value: chosen.value }];
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

function epochLabel(epoch: number): string {
	return `J${Number.isInteger(epoch) ? epoch.toFixed(1) : String(epoch)}`;
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

function displayedSpectralType(ps: TableRow): string | null {
	const host = ps.text('host_spectral_type');
	return spectralType(ps) ?? (host ? ltrIsolate(host) : null);
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

type FlameRows = Record<
	'radius' | 'luminosity' | 'mass' | 'age' | 'stage' | 'redshift' | 'correction',
	StarRowEntry | null
>;

/** The rows of one FLAME run. A mass that does not hold takes its age and
 *  stage with it. */
function flameRows(ps: TableRow, u: ReturnType<typeof units>, run: FlameRun): FlameRows {
	const column = (name: string) => `${name}_flame${run}`;
	const fit = flameFitHolds(ps, run);
	const stage = ps.number(column('evolstage'));
	return {
		radius: bounded(ps, m.star_stat_radius(), column('radius'), u.km, SOLAR_RADIUS_KM),
		luminosity: bounded(ps, m.star_stat_luminosity(), column('lum'), u.solarLuminosity),
		mass: fit ? bounded(ps, m.star_stat_mass(), column('mass'), u.solarMass) : null,
		age: fit ? bounded(ps, m.star_row_age(), column('age'), u.gigayear) : null,
		stage:
			fit && stage !== null ? row(m.star_row_evolutionary_stage(), evolutionaryStage(stage)) : null,
		redshift: bounded(ps, m.star_row_gravitational_redshift(), column('gravredshift'), u.kms),
		correction: measured(ps, m.star_row_bolometric_correction(), column('bc'), null)
	};
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

/** The three most useful available facts. */
export function starStats(record: ExtrasolarRecord): Stat[][] {
	const ps = pointSource(record);
	if (!ps) return [];
	const u = units();
	const out: (Stat | null)[] = [];
	const radius =
		ps.number('radius_flame') ??
		ps.number('radius_flame_spec') ??
		ps.number('radius_gspphot') ??
		ps.number('host_radius');
	const mass =
		(flameFitHolds(ps) ? ps.number('mass_flame') : null) ??
		(flameFitHolds(ps, '_spec') ? ps.number('mass_flame_spec') : null) ??
		ps.number('host_mass');
	if (radius !== null) {
		out.push({
			label: m.star_stat_radius(),
			value: joinParts({ value: sigFigures(radius * SOLAR_RADIUS_KM), unit: u.km })
		});
	} else if (mass !== null) {
		out.push({
			label: m.star_stat_mass(),
			value: joinParts({ value: sigFigures(mass), unit: u.solarMass })
		});
	}
	const distance = starDistance(ps, astrometricOrbit(record));
	const uncertain = uncertainty(distance);
	if (distance !== null) {
		out.push({
			label: m.star_stat_distance(),
			value: joinParts({ value: sigFigures(distance.pc * PC_LY), unit: u.ly }),
			tooltip: uncertain
		});
	}
	const teff = ps.number('teff_gspphot') ?? ps.number('host_teff');
	const spType = displayedSpectralType(ps);
	if (teff !== null) {
		out.push({
			label: m.star_stat_temperature(),
			value: formatTemperature({ value: teff, unit: 'kelvin' })
		});
	} else if (spType) {
		out.push({ label: m.star_stat_spectral_type(), value: spType });
	}
	const luminosity = ps.number('lum_flame') ?? ps.number('lum_flame_spec');
	if (out.length < 3 && luminosity !== null) {
		out.push({
			label: m.star_stat_luminosity(),
			value: joinParts({ value: sigFigures(luminosity), unit: u.solarLuminosity })
		});
	}
	const cards = out.filter((card): card is Stat => card !== null).slice(0, 3);
	return cards.length ? [cards] : [];
}

/** The sections of rows, in panel order; an empty section is left out. */
export function starSections(record: ExtrasolarRecord): StarSection[] {
	const ps = pointSource(record);
	if (!ps) return [];
	return pointSourceSections(ps, astrometricOrbit(record), units()).filter(
		(section) => section.rows.length > 0
	);
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
	error: string | null = null,
	scale = 1
): StarRowEntry | null {
	const value = float32Value(ps.number(name));
	if (value === null) return null;
	const err = error === null ? null : float32Value(ps.number(error));
	if (scale === 1) return { label, value: formatCatalogueQuantity(value, err, err, unit) };
	// The catalogue's decimals hold in its own unit only; its figures hold in both.
	const scaledError = err === null ? null : err * scale;
	return {
		label,
		value: formatMeasuredQuantity({
			value: value * scale,
			upperError: scaledError,
			lowerError: scaledError,
			unit,
			rawValue: value,
			roundLargeErrors: true
		})
	};
}

/** A distance with its bounds; with one bound or none, at the precision of a
 *  stat card rather than as an exact value. */
function distanceValue(distance: StarDistance, ly: string): string {
	const { lower, upper } = distance;
	if (lower !== null && upper !== null) {
		return withBounds(distance.pc * PC_LY, lower * PC_LY, upper * PC_LY, ly);
	}
	return joinParts({ value: sigFigures(distance.pc * PC_LY), unit: ly });
}

function pointSourceSections(
	ps: TableRow,
	orbit: TableRow | null,
	u: ReturnType<typeof units>
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
					value: distanceValue(distance, u.ly),
					tooltip: uncertainty(distance)
				}
			: catalogued(ps, m.star_row_distance(), 'host_distance', u.ly, 'host_distance_error', PC_LY),
		measured(ps, m.star_row_pm_ra(), 'pmra', 'pmra_error', u.masPerYear),
		measured(ps, m.star_row_pm_dec(), 'pmdec', 'pmdec_error', u.masPerYear),
		measured(ps, m.star_row_radial_velocity(), 'radial_velocity', 'radial_velocity_error', u.kms),
		bounded(ps, m.star_row_distance_photometric(), 'distance_gspphot', u.ly, PC_LY)
	];

	const g = ps.number('phot_g_mean_mag');
	const bp = ps.number('phot_bp_mean_mag');
	const rp = ps.number('phot_rp_mean_mag');
	const v = ps.number('v_mag');
	const spType = displayedSpectralType(ps);
	// TODO: Replace this precedence when the export supplies one canonical stellar fit.
	const photometricFit = flameRows(ps, u, '');
	const spectroscopicFit = flameRows(ps, u, '_spec');
	const fitted = (quantity: keyof FlameRows) =>
		photometricFit[quantity] ?? spectroscopicFit[quantity];
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
		v !== null
			? measured(ps, m.star_band_v(), 'v_mag', null, '', 2)
			: catalogued(ps, m.star_band_v(), 'host_v_mag'),
		g === null ? catalogued(ps, m.star_band_g(), 'host_g_mag') : null,
		catalogued(ps, m.star_band_k(), 'host_k_mag'),
		measured(ps, m.star_row_b_v(), 'b_v', 'b_v_error', '', 3),
		measured(ps, m.star_row_v_i(), 'v_i', 'v_i_error', '', 2),
		row(
			m.star_row_variability(),
			ps.text('phot_variable_flag') === 'VARIABLE' ? m.star_variable() : null
		),
		bounded(ps, m.star_row_extinction_a0(), 'azero_gspphot'),
		bounded(ps, m.star_row_extinction_g(), 'ag_gspphot'),
		bounded(ps, m.star_row_reddening(), 'ebpminrp_gspphot'),
		fitted('correction')
	];

	const teff = ps.number('teff_gspphot');
	const metallicity = metallicityRows(ps, orbit, u.dex);
	const physical: (StarRowEntry | null)[] = [
		teff !== null
			? {
					label: m.star_row_teff(),
					value: temperatureWithBounds(
						teff,
						ps.number('teff_gspphot_lower'),
						ps.number('teff_gspphot_upper')
					)
				}
			: ps.number('host_teff') !== null
				? {
						label: m.star_row_teff(),
						value: formatTemperature({ value: ps.number('host_teff')!, unit: 'kelvin' })
					}
				: null,
		ps.number('logg_gspphot') !== null
			? bounded(ps, m.star_row_logg(), 'logg_gspphot')
			: catalogued(ps, m.star_row_logg(), 'host_logg'),
		...metallicity,
		metallicity.length === 0
			? catalogued(ps, m.exoplanet_row_metallicity(), 'host_metallicity', u.dex)
			: null,
		fitted('radius') ??
			bounded(ps, m.star_row_radius_photometric(), 'radius_gspphot', u.km, SOLAR_RADIUS_KM) ??
			catalogued(ps, m.star_stat_radius(), 'host_radius', u.km, null, SOLAR_RADIUS_KM),
		fitted('luminosity'),
		fitted('mass') ??
			catalogued(ps, m.star_stat_mass(), 'host_mass', m.exoplanet_symbol_solar_mass()),
		fitted('age') ?? catalogued(ps, m.star_row_age(), 'host_age', m.symbol_gigaannum()),
		fitted('redshift'),
		measured(ps, m.star_row_line_broadening(), 'vbroad', 'vbroad_error', u.kms)
	];

	const classification = rows([row(m.star_stat_spectral_type(), spType), fitted('stage')]);

	return [
		{ key: 'classification', title: m.classification(), rows: classification },
		{ key: 'position', title: m.star_section_position(), rows: rows(position) },
		{ key: 'brightness', title: m.star_section_brightness(), rows: rows(brightness) },
		{ key: 'physical', title: m.physical_properties(), rows: rows(physical) }
	];
}
