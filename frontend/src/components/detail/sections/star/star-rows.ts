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
	flameFitHolds,
	measuredRadiusSolar,
	starMass,
	type FlameRun
} from '$lib/scene/starfield/record';
import {
	boundErrors,
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
	powerOfTen,
	sigFigures
} from '$lib/format/quantities';
import { ltrIsolate } from '$lib/format/bidi';
import { formatCompactKm } from '$lib/format/distance';
import { formatTemperature, formatTemperatureRange } from '$lib/format/temperature';
import { formatMass, massComparison, SOLAR_MASS_KG, sizeComparison } from '$lib/format/mass';
import { formatLuminosity, luminosityComparison, SOLAR_LUMINOSITY_W } from '$lib/format/light';
import { SOLAR_RADIUS_KM } from '$lib/math/units';
import type { Stat } from '../kit/StatCard.svelte';
import { chooseMetallicity, type MetallicityQuantity } from './metallicity';
import type { EntityRef } from '$lib/fetch/objects/object-data';
import type { SystemNode } from '$lib/fetch/extrasolar/systems';

export const POINT_SOURCE_SLUG = 'point-source';

/** Light years in one parsec. */
export const PC_LY = PC_AU / 63_241.077;
/** Magnitudes per unit of a flux's relative error. */
const MAG_PER_FLUX = 2.5 / Math.LN10;

export interface StarRowEntry {
	label: string;
	value: string;
	/** Where the value leads, off the site. */
	href?: string;
	/** What this particular value is. */
	tooltip?: string;
	/** What the quantity is, on the label. */
	definition?: string;
	/** A word on how the value was had: assumed, computed. */
	note?: string;
	/** Objects, linked, in place of the value. */
	entities?: EntityRef[];
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
	'iau/wgsn': { label: m.star_xid_iau },
	'star-system/msc': { label: m.star_xid_msc },
	'star-system/wds': { label: m.star_xid_wds }
};

/** The catalogues that join the Point source row hold their ids in its columns.
 *  PASTEL, the GCVS and ATNF name a star as SIMBAD does, so SIMBAD finds the
 *  star by that name. `simbad` is what SIMBAD writes before it, null for no link. */
const JOINED_IDS: [column: string, label: () => string, simbad: string | null][] = [
	['pastel_designation', m.star_xid_pastel, ''],
	['apogee_id', m.star_xid_apogee, null],
	['lamost_id', m.star_xid_lamost, null],
	['gcvs_name', m.star_xid_gcvs, 'V* '],
	['atnf_name', m.star_xid_atnf, 'PSR ']
];

/** Cross-ids not shown. A SIMBAD oid, a NASA Exoplanet Archive row and the
 *  claim that keeps the ID of a system or a held star are internal keys; a
 *  literature key and the other planet catalogues' keys repeat another id or
 *  the name of the star. */
const HIDDEN_CATALOGUES = new Set([
	'simbad/oid',
	'literature/star',
	'nasa-exoplanet-archive/pscomppars',
	'exoplanet-eu/catalog',
	'open-exoplanet-catalogue/systems',
	'star-system/simbad',
	'star-system/el-badry',
	'star-system/primary',
	'star-system/member'
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
	simbad: string | null
): StarRowEntry | null {
	if (!id || simbad === null) return row(label(), id);
	return row(label(), id.replace(SIMBAD_TYPE_PREFIX, ''), SIMBAD + encodeURIComponent(simbad + id));
}

/** Catalogue identifiers shown with the object's other links. */
export function starIdentifiers(record: ExtrasolarRecord): StarRowEntry[] {
	const ps = pointSource(record);
	return rows([
		...record.metadata.crossIds.filter((x) => !LINKED_CATALOGUES.has(x.catalogue)).map(crossIdRow),
		...JOINED_IDS.map(([column, label, simbad]) => joinedIdRow(ps?.text(column), label, simbad)),
		row(m.star_xid_spicy(), ps?.number('spicy_id')?.toString())
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
	'brown dwarf': m.exoplanet_class_brown_dwarf,
	'binary star': m.star_class_binary_star,
	'multiple star': m.star_class_multiple_star
};

/** The class a Metadata row names, in words. */
export function starClassLabel(cls: string | null): string {
	return (cls && CLASS_LABELS[cls]?.()) || (cls ?? '');
}

export function units() {
	return {
		mas: m.symbol_milliarcsecond(),
		masPerYear: m.symbol_milliarcsecond_per_year(),
		ly: m.symbol_light_year(),
		kms: m.symbol_kilometre_per_second(),
		dex: m.symbol_dex(),
		km: formatUnit('kilometre', true),
		gigayear: m.symbol_gigaannum()
	};
}

function magnitudeError(row: TableRow, fluxOverError: string): number | null {
	const foe = row.number(fluxOverError);
	return foe !== null && foe > 0 ? MAG_PER_FLUX / foe : null;
}

/** Rows whose value is there; a null value leaves its row out. */
export function rows(entries: (StarRowEntry | null)[]): StarRowEntry[] {
	return entries.filter((entry): entry is StarRowEntry => entry !== null);
}

export function row(
	label: string,
	value: string | null | undefined,
	href?: string
): StarRowEntry | null {
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

/** `power` as for `formatMeasuredQuantity`. */
function bounded(
	ps: TableRow,
	label: string,
	name: string,
	unit = '',
	scale = 1,
	power?: number
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
				? formatMeasuredQuantity({ value: value * scale, unit, power, maxSignificantDigits: 3 })
				: withBounds(value * scale, lower * scale, upper * scale, unit, true, power)
	};
}

/** A star's diameter row, with what `column`'s radius comes to against the Sun
 *  (or Jupiter or Earth). */
function diameterRow(
	ps: TableRow,
	entry: StarRowEntry | null,
	column: string
): StarRowEntry | null {
	const radius = ps.number(column);
	if (!entry || radius === null) return entry;
	return { ...entry, tooltip: sizeComparison(radius * SOLAR_RADIUS_KM) };
}

/** The row of a measured diameter, with the column that gives it as source. */
function measuredDiameterRow(ps: TableRow, u: ReturnType<typeof units>): StarRowEntry | null {
	const radius = measuredRadiusSolar(ps);
	if (radius === null) return null;
	return {
		label: m.diameter(),
		value: formatMeasuredQuantity({
			value: 2 * radius * SOLAR_RADIUS_KM,
			unit: u.km,
			maxSignificantDigits: 3
		}),
		tooltip: sizeComparison(radius * SOLAR_RADIUS_KM)
	};
}

/** A quantity in solar units, in SI on the power of ten of its value, and the
 *  comparison of that SI value and its errors. */
interface SolarQuantity {
	label: () => string;
	definition?: () => string;
	unit: () => string;
	perSolar: number;
	compare: (si: number, upperError: number | null, lowerError: number | null) => string | undefined;
}

const SOLAR_MASS: SolarQuantity = {
	label: m.star_stat_mass,
	unit: () => formatUnit('kilogram', true),
	perSolar: SOLAR_MASS_KG,
	compare: massComparison
};

const SOLAR_LUMINOSITY: SolarQuantity = {
	label: m.star_stat_luminosity,
	definition: m.tooltip_luminosity,
	unit: m.symbol_watt,
	perSolar: SOLAR_LUMINOSITY_W,
	compare: luminosityComparison
};

/** A value in solar units, in SI, with what it comes to against the Sun (or
 *  Jupiter or Earth, for a mass). A fit's percentiles bound it; a catalogue
 *  value keeps the figures it was published with. */
function solarRow(
	ps: TableRow,
	quantity: SolarQuantity,
	name: string,
	catalogue = false
): StarRowEntry | null {
	const solar = ps.number(name);
	if (solar === null) return null;
	const si = solar * quantity.perSolar;
	const args = [ps, quantity.label(), name, quantity.unit()] as const;
	const power = powerOfTen(si, 3);
	const row = catalogue
		? catalogued(...args, null, quantity.perSolar, power)
		: bounded(...args, quantity.perSolar, power);
	const errors = boundErrors(solar, ps.number(`${name}_lower`), ps.number(`${name}_upper`));
	const inSi = (error: number | undefined) =>
		error === undefined ? null : error * quantity.perSolar;
	return {
		...row!,
		tooltip: quantity.compare(si, inSi(errors?.upperError), inSi(errors?.lowerError)),
		definition: quantity.definition?.()
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

export function epochLabel(epoch: number): string {
	return `J${Number.isInteger(epoch) ? epoch.toFixed(1) : String(epoch)}`;
}

function pointSource(record: ExtrasolarRecord): TableRow | null {
	return record.rows.get(POINT_SOURCE_SLUG) ?? null;
}

/** A spectral type, a catalogue code, as an LTR isolate. In RTL text the
 *  punctuation at its ends ("A0m...", "B8Ia:") then stays in place. */
export function spectralType(code: string | null): string | null {
	return code ? ltrIsolate(code) : null;
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
	'diameter' | 'luminosity' | 'age' | 'stage' | 'redshift' | 'correction',
	StarRowEntry | null
>;

/** The rows of one FLAME run. A mass that does not hold takes its age and
 *  stage with it. The mass row is {@link massRow}. */
function flameRows(ps: TableRow, u: ReturnType<typeof units>, run: FlameRun): FlameRows {
	const column = (name: string) => `${name}_flame${run}`;
	const fit = flameFitHolds(ps, run);
	const stage = ps.number(column('evolstage'));
	return {
		diameter: diameterRow(
			ps,
			bounded(ps, m.diameter(), column('radius'), u.km, 2 * SOLAR_RADIUS_KM),
			column('radius')
		),
		luminosity: solarRow(ps, SOLAR_LUMINOSITY, column('lum')),
		age: fit ? bounded(ps, m.star_row_age(), column('age'), u.gigayear) : null,
		stage:
			fit && stage !== null ? row(m.star_row_evolutionary_stage(), evolutionaryStage(stage)) : null,
		redshift: bounded(ps, m.star_row_gravitational_redshift(), column('gravredshift'), u.kms),
		correction: measured(ps, m.star_row_bolometric_correction(), column('bc'), null)
	};
}

/** The row of the mass that {@link starMass} chooses. A FLAME mass shows its
 *  bounds. */
function massRow(ps: TableRow): StarRowEntry | null {
	const mass = starMass(ps);
	return mass && solarRow(ps, SOLAR_MASS, mass.source, mass.source === 'host_mass');
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

/** A distance card. */
export function distanceStat(pc: number, tooltip?: string): Stat {
	return {
		label: m.star_stat_distance(),
		value: joinParts({ value: sigFigures(pc * PC_LY), unit: units().ly }),
		tooltip
	};
}

/** The distance card of a record with a Point source row. */
export function pointDistanceStat(ps: TableRow, orbit: TableRow | null): Stat | null {
	const distance = starDistance(ps, orbit);
	return distance && distanceStat(distance.pc, uncertainty(distance));
}

/** The three most useful available facts. */
export function starStats(record: ExtrasolarRecord): Stat[][] {
	const ps = pointSource(record);
	if (!ps) return [];
	const out: (Stat | null)[] = [];
	const radius =
		measuredRadiusSolar(ps) ??
		ps.number('radius_flame') ??
		ps.number('radius_flame_spec') ??
		ps.number('radius_gspphot') ??
		ps.number('host_radius');
	const mass = starMass(ps)?.solar ?? null;
	if (radius !== null) {
		out.push({
			label: m.diameter(),
			value: formatCompactKm(2 * radius * SOLAR_RADIUS_KM),
			tooltip: sizeComparison(radius * SOLAR_RADIUS_KM)
		});
	} else if (mass !== null) {
		out.push({
			label: m.star_stat_mass(),
			value: formatMass(mass * SOLAR_MASS_KG),
			tooltip: massComparison(mass * SOLAR_MASS_KG)
		});
	}
	const distance = pointDistanceStat(ps, astrometricOrbit(record));
	if (distance) out.push(distance);
	const teff = ps.number('teff_gspphot') ?? ps.number('host_teff');
	const spType = spectralType(record.metadata.spectralType);
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
			value: formatLuminosity(luminosity * SOLAR_LUMINOSITY_W),
			tooltip: luminosityComparison(luminosity * SOLAR_LUMINOSITY_W)
		});
	}
	const cards = out.filter((card): card is Stat => card !== null).slice(0, 3);
	return cards.length ? [cards] : [];
}

/** The sections of rows, in panel order; an empty section is left out. The
 *  point of a `node` holds several stars, so it gives only what is true of the
 *  point: the fits of its row assume one star. */
export function starSections(record: ExtrasolarRecord, node?: SystemNode): StarSection[] {
	const ps = pointSource(record);
	if (!ps) return [];
	return pointSourceSections(
		ps,
		astrometricOrbit(record),
		spectralType(record.metadata.spectralType),
		units(),
		!node
	).filter((section) => section.rows.length > 0);
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
	scale = 1,
	power?: number
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
			roundLargeErrors: true,
			power
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
	spType: string | null,
	u: ReturnType<typeof units>,
	oneStar: boolean
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
		oneStar ? bounded(ps, m.star_row_distance_photometric(), 'distance_gspphot', u.ly, PC_LY) : null
	];

	const g = ps.number('phot_g_mean_mag');
	const bp = ps.number('phot_bp_mean_mag');
	const rp = ps.number('phot_rp_mean_mag');
	const v = ps.number('v_mag');
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
		...(oneStar
			? [
					bounded(ps, m.star_row_extinction_a0(), 'azero_gspphot'),
					bounded(ps, m.star_row_extinction_g(), 'ag_gspphot'),
					bounded(ps, m.star_row_reddening(), 'ebpminrp_gspphot'),
					fitted('correction')
				]
			: [])
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
		measuredDiameterRow(ps, u) ??
			fitted('diameter') ??
			diameterRow(
				ps,
				bounded(ps, m.star_row_diameter_photometric(), 'radius_gspphot', u.km, 2 * SOLAR_RADIUS_KM),
				'radius_gspphot'
			) ??
			diameterRow(
				ps,
				catalogued(ps, m.diameter(), 'host_radius', u.km, null, 2 * SOLAR_RADIUS_KM),
				'host_radius'
			),
		fitted('luminosity'),
		massRow(ps),
		fitted('age') ?? catalogued(ps, m.star_row_age(), 'host_age', m.symbol_gigaannum()),
		fitted('redshift'),
		measured(ps, m.star_row_line_broadening(), 'vbroad', 'vbroad_error', u.kms)
	];

	const classification = oneStar
		? rows([row(m.star_stat_spectral_type(), spType), fitted('stage')])
		: [];

	return [
		{ key: 'classification', title: m.classification(), rows: classification },
		{ key: 'position', title: m.star_section_position(), rows: rows(position) },
		{ key: 'brightness', title: m.star_section_brightness(), rows: rows(brightness) },
		{ key: 'physical', title: m.physical_properties(), rows: oneStar ? rows(physical) : [] }
	];
}
