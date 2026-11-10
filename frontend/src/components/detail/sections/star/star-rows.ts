/** A star's most useful values, grouped by meaning. */

import * as m from '$lib/paraglide/messages.js';
import type { CrossId } from '$lib/fetch/extrasolar/container';
import {
	astrometricOrbit,
	distanceParallax,
	LITERATURE,
	STAR_SYSTEMS,
	starDistance,
	type ExtrasolarRecord,
	type StarDistance,
	POINT_SOURCE_SLUG,
	type StarRadius,
	type StarRadiusSource,
	type TableRow
} from '$lib/fetch/extrasolar/lookup';
import { starSourceName } from '$lib/credits/star-sources';
import { PC_AU } from '$lib/scene/starfield/tree';
import {
	flameFitHolds,
	isCompact,
	starMass,
	starTeff,
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
	fixed,
	formatCatalogueQuantity,
	formatMeasuredQuantity,
	formatUnit,
	joinParts,
	powerOfTen,
	sigFigures
} from '$lib/format/quantities';
import { ltrIsolate } from '$lib/format/bidi';
import { formatCompactKm } from '$lib/format/distance';
import {
	formatKelvin,
	formatKelvinRange,
	formatTemperature,
	formatTemperatureRange
} from '$lib/format/temperature';
import { formatMass, massComparison, SOLAR_MASS_KG, sizeComparison } from '$lib/format/mass';
import { formatLuminosity, luminosityComparison, SOLAR_LUMINOSITY_W } from '$lib/format/light';
import { formatGees, formatMs2 } from '$lib/format/gravity';
import { formedAgo } from '$lib/format/age';
import { densityComparison } from '$lib/format/density';
import { metallicityComparison } from '$lib/format/metallicity';
import { SOLAR_RADIUS_KM } from '$lib/math/units';
import { G0_M_S2 } from '$lib/math/travel/constants';
import { ROUGH_TIER } from '$lib/fetch/extrasolar/interior';
import type { Stat } from '../kit/StatCard.svelte';
import { chooseMetallicity, type MetallicityQuantity } from './metallicity';
import type { EntityRef, InteriorBlock, Temperatures } from '$lib/fetch/objects/object-data';
import type { SystemCitation, SystemNode } from '$lib/fetch/extrasolar/systems';
import type { StarStructure } from '../../state/star-interior.svelte';

/** Light years in one parsec. */
export const PC_LY = PC_AU / 63_241.077;

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
	/** The photosphere, as a temperature scale under the rows. */
	temperature?: StarTemperature;
	/** The section links to the Structure tab. */
	structure?: true;
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

/** The parts of a tooltip that are there, joined; undefined for none. */
export function hint(...parts: (string | null | undefined)[]): string | undefined {
	return parts.filter(Boolean).join(' · ') || undefined;
}

/** Where a value is from: the work that its source cites, else the source. */
export function sourceOf(
	source: string | null,
	references: readonly SystemCitation[] = []
): string | undefined {
	if (!source) return undefined;
	const short = references.find((work) => work.source === source)?.short;
	return `${m.source_prefix()} ${short ?? starSourceName(source)}`;
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

/** A value with its percentiles, times `scale`. `power` as for
 *  `formatMeasuredQuantity`. */
function boundedValue(
	value: number,
	lower: number | null,
	upper: number | null,
	unit: string,
	scale: number,
	power?: number
): string {
	if (scale === 1) return withBounds(value, lower, upper, unit);
	return lower === null || upper === null
		? formatMeasuredQuantity({ value: value * scale, unit, power, maxSignificantDigits: 3 })
		: withBounds(value * scale, lower * scale, upper * scale, unit, true, power);
}

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
	const [lower, upper] = [ps.number(`${name}_lower`), ps.number(`${name}_upper`)];
	return { label, value: boundedValue(value, lower, upper, unit, scale, power) };
}

/** The bounds of a Gaia radius, by its source. */
const FIT_RADII: Partial<Record<StarRadiusSource, string>> = {
	'gaia-dr3-flame': 'radius_flame',
	'gaia-dr3-flame-spec': 'radius_flame_spec',
	'gaia-dr3-gspphot': 'radius_gspphot'
};
const CATALOGUE_RADII = new Set<StarRadiusSource>([
	'nasa-exoplanet-archive',
	'exoplanet-eu',
	'open-exoplanet-catalogue'
]);

/**
 * The diameter row of a star's radius, the same on a star's page and a held
 * star's. A Gaia radius takes its bounds from the Point source row `fit`, a
 * catalogue's its `error`. The tooltip names the source, or the work of
 * `references` that gives it.
 */
export function diameterRow(
	radius: StarRadius | null,
	fit: TableRow | null,
	error: number | null,
	references: readonly SystemCitation[] = []
): StarRowEntry | null {
	if (!radius) return null;
	const { solar, source } = radius;
	const { km } = units();
	const scale = 2 * SOLAR_RADIUS_KM;
	const column = fit && FIT_RADII[source];
	const value = column
		? boundedValue(solar, fit.number(`${column}_lower`), fit.number(`${column}_upper`), km, scale)
		: CATALOGUE_RADII.has(source)
			? cataloguedValue(float32Value(solar)!, float32Value(error), km, scale)
			: formatMeasuredQuantity({ value: solar * scale, unit: km, maxSignificantDigits: 3 });
	return {
		label: source === 'gaia-dr3-gspphot' ? m.star_row_diameter_photometric() : m.diameter(),
		value,
		tooltip: hint(sizeComparison(solar * SOLAR_RADIUS_KM), sourceOf(source, references))
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
 *  Jupiter or Earth, for a mass). Its `_lower` and `_upper` columns bound it.
 *  A `catalogue` value keeps the figures that the planet catalogue gives. */
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
	const errors = catalogue
		? null
		: boundErrors(solar, ps.number(`${name}_lower`), ps.number(`${name}_upper`));
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
	return [
		{
			label: METALLICITY_LABELS[chosen.quantity](),
			value: chosen.value,
			tooltip: metallicityComparison(chosen.dex, chosen.quantity)
		}
	];
}

/** An age in Gyr with its bounds, and when the star formed. */
function ageRow(ps: TableRow, name: string, u: ReturnType<typeof units>): StarRowEntry | null {
	const entry = bounded(ps, m.star_row_age(), name, u.gigayear);
	const gyr = ps.number(name);
	if (!entry || gyr === null) return entry;
	const lower = ps.number(`${name}_lower`);
	const upper = ps.number(`${name}_upper`);
	// With no bounds, the row shows two decimals of a Ga.
	const figure =
		lower === null || upper === null || !(upper > lower)
			? fixed(gyr, 2)
			: withBounds(gyr, lower, upper);
	return { ...entry, tooltip: formedAgo(figure) };
}

/** A planet catalogue's age of its host in Gyr, and when the star formed. */
export function hostAgeRow(age: number | null): StarRowEntry | null {
	const gyr = float32Value(age);
	if (gyr === null) return null;
	return {
		label: m.star_row_age(),
		value: cataloguedValue(gyr, null, m.symbol_gigaannum(), 1),
		tooltip: formedAgo(formatMeasuredQuantity({ value: gyr }))
	};
}

/** The percentiles of a temperature (K), where they do not round alike. */
function temperatureBounds(low: number | null, high: number | null): string | undefined {
	if (low === null || high === null) return undefined;
	const lowK = { value: low, unit: 'kelvin' };
	const highK = { value: high, unit: 'kelvin' };
	if (formatTemperature(lowK) === formatTemperature(highK)) return undefined;
	return ltrIsolate(formatTemperatureRange(lowK, highK));
}

/** The centre temperature of an interior block: its range, else its value. */
export function centreTemperature(block: InteriorBlock): string | null {
	const range = block.centre_temperature_range_k;
	if (range) return formatKelvinRange(range[0], range[1]);
	const value = block.centre_temperature_k;
	return value === undefined ? null : formatKelvin(value);
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

type FlameRows = Record<'age' | 'stage' | 'redshift', StarRowEntry | null>;

/** The rows of one FLAME run; none for a compact star, which FLAME fits as a
 *  normal star. A mass that does not hold takes its age and stage with it.
 *  The mass row is {@link massRow}, the diameter row {@link diameterRow}. */
function flameRows(ps: TableRow, u: ReturnType<typeof units>, run: FlameRun): FlameRows {
	if (isCompact(ps)) return { age: null, stage: null, redshift: null };
	const column = (name: string) => `${name}_flame${run}`;
	const fit = flameFitHolds(ps, run);
	const stage = ps.number(column('evolstage'));
	return {
		age: fit ? ageRow(ps, column('age'), u) : null,
		stage:
			fit && stage !== null ? row(m.star_row_evolutionary_stage(), evolutionaryStage(stage)) : null,
		redshift: bounded(ps, m.star_row_gravitational_redshift(), column('gravredshift'), u.kms)
	};
}

/** The row of the mass that {@link starMass} chooses. A FLAME or paper mass
 *  shows its bounds, a planet catalogue's mass its figures. */
function massRow(ps: TableRow): StarRowEntry | null {
	const mass = starMass(ps);
	if (!mass) return null;
	return solarRow(ps, SOLAR_MASS, mass.source, mass.source === 'host_mass');
}

/** The Teff sources that read a B − V colour. Their values are estimates. */
const ESTIMATED_TEFF = new Set(['casagrande-2010', 'flower-1996']);
/** The luminosity source that reads a V magnitude through a bolometric correction. */
const ESTIMATED_LUMINOSITY = 'bolometric-correction';
/** The V source that converts Gaia's G and BP − RP. */
const CONVERTED_V = 'riello-2021';
/** The `extinction_source` of an absolute V that takes no A_V for want of one. */
const UNKNOWN_EXTINCTION = 'unknown';

function estimatedTeff(ps: TableRow): boolean {
	return ESTIMATED_TEFF.has(ps.text('teff_source') ?? '');
}

function estimatedLuminosity(ps: TableRow): boolean {
	return ps.text('luminosity_source') === ESTIMATED_LUMINOSITY;
}

/** The photosphere of a star, for a section's temperature scale. */
export interface StarTemperature {
	temperatures: Temperatures;
	/** The bounds of the reading. */
	valueTooltip?: string;
	/** Why the reading is an estimate. */
	estimatedNote?: string;
}

/** The temperature scale of a Teff in K. */
export function photosphere(
	k: number | null,
	estimated = false,
	valueTooltip?: string
): StarTemperature | undefined {
	if (k === null) return undefined;
	return {
		temperatures: {
			readings: [{ part: 'photosphere', kind: 'mean', k }],
			origin: estimated ? 'estimated' : 'measured'
		},
		valueTooltip,
		estimatedNote: estimated ? m.tooltip_star_teff_estimated() : undefined
	};
}

function teffScale(ps: TableRow): StarTemperature | undefined {
	return photosphere(
		ps.number('teff'),
		estimatedTeff(ps),
		temperatureBounds(ps.number('teff_lower'), ps.number('teff_upper'))
	);
}

/** cm/s² in one m/s². */
const CM_PER_M = 100;

/** The photosphere gravity of a log g in log(cm/s²) with its bounds, in
 *  gees as the Sun's reads, and in SI on the value. */
export function gravityRow(
	logg: number | null,
	lower: number | null = null,
	upper: number | null = null
): StarRowEntry | null {
	if (logg === null) return null;
	const ms2 = 10 ** logg / CM_PER_M;
	const gees = (log: number) => 10 ** log / CM_PER_M / G0_M_S2;
	return {
		label: m.gravity_photosphere(),
		definition: m.tooltip_gravity_photosphere(),
		value: ltrIsolate(
			lower === null || upper === null
				? formatGees(ms2)
				: withBounds(gees(logg), gees(lower), gees(upper), m.symbol_standard_gravity(), true)
		),
		tooltip: ltrIsolate(formatMs2(ms2))
	};
}

function luminosityRow(ps: TableRow): StarRowEntry | null {
	const entry = solarRow(ps, SOLAR_LUMINOSITY, 'luminosity');
	if (!entry || !estimatedLuminosity(ps)) return entry;
	return { ...entry, note: m.exoplanet_estimated() };
}

/** The tooltip of an absolute V from a converted V or with no known extinction. */
function absoluteVTooltip(ps: TableRow): string | undefined {
	const converted = ps.text('apparent_v_source') === CONVERTED_V;
	const unknown = ps.text('extinction_source') === UNKNOWN_EXTINCTION;
	if (converted && unknown) return m.star_absolute_v_converted_no_extinction();
	if (converted) return m.star_absolute_v_converted();
	return unknown ? m.star_absolute_v_no_extinction() : undefined;
}

/** The V magnitude and the absolute V magnitude of a point. */
function magnitudeRows(ps: TableRow): (StarRowEntry | null)[] {
	const apparent = ps.number('apparent_v');
	const absolute = ps.number('absolute_v');
	return [
		apparent === null
			? null
			: {
					label: m.star_row_apparent_v(),
					definition: m.tooltip_apparent_magnitude(),
					value: plusMinus(apparent, null),
					tooltip: ps.text('apparent_v_source') === CONVERTED_V ? m.star_v_converted() : undefined
				},
		absolute === null
			? null
			: {
					label: m.star_row_absolute_v(),
					definition: m.tooltip_absolute_magnitude(),
					value: plusMinus(absolute, null),
					tooltip: absoluteVTooltip(ps)
				}
	];
}

/** Gaia's variability flag of a point. */
function variabilityRow(ps: TableRow): StarRowEntry | null {
	const variable = ps.text('phot_variable_flag') === 'VARIABLE';
	return row(m.star_row_variability(), variable ? m.star_variable() : null);
}

/** g/cm³ of one solar mass in a sphere of one solar radius. */
const SOLAR_MEAN_DENSITY =
	(SOLAR_MASS_KG * 1000) / ((4 / 3) * Math.PI * (SOLAR_RADIUS_KM * 1e5) ** 3);
/** Densities outside this range (g/cm³) read on their power of ten. A red
 *  giant is a ten-millionth of water, and a white dwarf a million times it. */
const PLAIN_DENSITY: [number, number] = [0.01, 1e4];

/** The mean density of `mass` M☉ in a sphere of `radius` R☉. */
export function meanDensityRow(mass: number | null, radius: number | null): StarRowEntry | null {
	if (mass === null || radius === null || !(radius > 0)) return null;
	const density = (mass / radius ** 3) * SOLAR_MEAN_DENSITY;
	const plain = density >= PLAIN_DENSITY[0] && density < PLAIN_DENSITY[1];
	return {
		label: m.property_name_density(),
		value: formatMeasuredQuantity({
			value: density,
			unit: formatUnit('gram_per_cubic_centimetre', true),
			maxSignificantDigits: 3,
			power: plain ? undefined : powerOfTen(density, 3)
		}),
		tooltip: densityComparison(density)
	};
}

/** Distance group sources as sure as a 5σ parallax: a distance chosen from a
 *  paper, a 5σ SIMBAD parallax, and the shared distance of the star's system. */
const SURE_SOURCES = new Set([LITERATURE, 'simbad-parallax', STAR_SYSTEMS]);

/** Why a distance is uncertain; undefined for one from a 5σ parallax or a sure source. */
function uncertainty(distance: StarDistance | null): string | undefined {
	if (!distance || distance.from === 'parallax' || SURE_SOURCES.has(distance.source ?? '')) {
		return undefined;
	}
	return distance.from === 'suspect parallax'
		? m.star_distance_suspect()
		: m.star_distance_uncertain();
}

/** The note of a distance from the star's system. The parallax row shows the
 *  star's own parallax, so the two do not agree. Only rows carry it: a card
 *  note is one line, too narrow for it. */
function systemNote(distance: StarDistance | null): string | undefined {
	return distance?.source === STAR_SYSTEMS ? m.star_distance_system() : undefined;
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

/** The diameter card of a star of `radius` solar radii. */
export function diameterStat(radius: number): Stat {
	return {
		label: m.diameter(),
		value: formatCompactKm(2 * radius * SOLAR_RADIUS_KM),
		tooltip: sizeComparison(radius * SOLAR_RADIUS_KM)
	};
}

/** The mass card of a star of `mass` solar masses. */
export function massStat(mass: number): Stat {
	const kg = mass * SOLAR_MASS_KG;
	return { label: m.star_stat_mass(), value: formatMass(kg), tooltip: massComparison(kg) };
}

/** The three most useful available facts. */
export function starStats(record: ExtrasolarRecord): Stat[][] {
	const ps = pointSource(record);
	if (!ps) return [];
	const out: (Stat | null)[] = [];
	const radius = record.metadata.radius?.solar ?? null;
	const mass = starMass(ps)?.solar ?? null;
	if (radius !== null) out.push(diameterStat(radius));
	else if (mass !== null) out.push(massStat(mass));
	const distance = pointDistanceStat(ps, astrometricOrbit(record));
	if (distance) out.push(distance);
	const teff = starTeff(ps);
	const spType = spectralType(record.metadata.spectralType);
	if (teff !== null) {
		out.push({
			label: m.star_stat_temperature(),
			value: formatTemperature({ value: teff, unit: 'kelvin' }),
			note: estimatedTeff(ps) ? m.exoplanet_estimated() : undefined
		});
	} else if (spType) {
		out.push({ label: m.star_stat_spectral_type(), value: spType });
	}
	const luminosity = ps.number('luminosity');
	if (out.length < 3 && luminosity !== null) {
		out.push({
			label: m.star_stat_luminosity(),
			value: formatLuminosity(luminosity * SOLAR_LUMINOSITY_W),
			tooltip: luminosityComparison(luminosity * SOLAR_LUMINOSITY_W),
			note: estimatedLuminosity(ps) ? m.exoplanet_estimated() : undefined
		});
	}
	const cards = out.filter((card): card is Stat => card !== null).slice(0, 3);
	return cards.length ? [cards] : [];
}

/** The interior of a star that the Structure tab draws. */
export type StarStructureRows = Pick<StarStructure, 'interior' | 'block'>;

/** The sections of rows, in panel order; an empty section is left out, but
 *  not one that links to the Structure tab. The point of a `node` holds
 *  several stars, so it gives only what is true of the point: the fits of its
 *  row assume one star. `structure` adds the centre of the star and the link
 *  to its Structure tab. */
export function starSections(
	record: ExtrasolarRecord,
	{ node, structure }: { node?: SystemNode; structure?: StarStructureRows | null } = {}
): StarSection[] {
	const ps = pointSource(record);
	if (!ps) return [];
	return pointSourceSections(
		ps,
		record.metadata.radius,
		astrometricOrbit(record),
		spectralType(record.metadata.spectralType),
		units(),
		!node,
		structure ?? null
	).filter((section) => section.rows.length > 0 || section.temperature || section.structure);
}

/** Significant figures a float32 column holds: 1.4 reads back 1.39999998. */
const FLOAT32_DIGITS = 7;

function float32Value(value: number | null): number | null {
	return value === null ? null : Number(value.toPrecision(FLOAT32_DIGITS));
}

/** A value of an exoplanet catalogue and its error, times `scale`, at the
 *  digits it gave. */
function cataloguedValue(
	value: number,
	err: number | null,
	unit: string,
	scale: number,
	power?: number
): string {
	if (scale === 1) return formatCatalogueQuantity(value, err, err, unit);
	// The catalogue's decimals hold in its own unit only; its figures hold in both.
	const scaledError = err === null ? null : err * scale;
	return formatMeasuredQuantity({
		value: value * scale,
		upperError: scaledError,
		lowerError: scaledError,
		unit,
		rawValue: value,
		roundLargeErrors: true,
		power
	});
}

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
	return { label, value: cataloguedValue(value, err, unit, scale, power) };
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

/** The centre temperature that the Interior section shows. A rough fit shows
 *  none. */
export function shownCentreTemperature(structure: StarStructureRows | null): string | null {
	return structure && structure.interior.tier !== ROUGH_TIER
		? centreTemperature(structure.block)
		: null;
}

/** The interior rows of a star: its mass, its mean density at `radius`, and
 *  the centre temperature of its interior. A section with layers links to the
 *  Structure tab. */
function interiorSection(
	ps: TableRow,
	radius: StarRadius | null,
	structure: StarStructureRows | null
): Pick<StarSection, 'rows' | 'structure'> {
	return {
		rows: rows([
			massRow(ps),
			meanDensityRow(starMass(ps)?.solar ?? null, radius?.solar ?? null),
			row(m.temperature_of_core(), shownCentreTemperature(structure))
		]),
		structure: structure?.block.layers?.length ? true : undefined
	};
}

/** A planet catalogue's [Fe/H] of its host. */
export function hostMetallicityRow(metallicity: number | null): StarRowEntry | null {
	const dex = float32Value(metallicity);
	if (dex === null) return null;
	return {
		label: m.exoplanet_row_metallicity(),
		value: cataloguedValue(dex, null, m.symbol_dex(), 1),
		tooltip: metallicityComparison(dex, 'feh')
	};
}

function pointSourceSections(
	ps: TableRow,
	radius: StarRadius | null,
	orbit: TableRow | null,
	spType: string | null,
	u: ReturnType<typeof units>,
	oneStar: boolean,
	structure: StarStructureRows | null
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
					tooltip: uncertainty(distance),
					note: systemNote(distance)
				}
			: catalogued(ps, m.star_row_distance(), 'host_distance', u.ly, 'host_distance_error', PC_LY),
		measured(ps, m.star_row_pm_ra(), 'pmra', 'pmra_error', u.masPerYear),
		measured(ps, m.star_row_pm_dec(), 'pmdec', 'pmdec_error', u.masPerYear),
		measured(ps, m.star_row_radial_velocity(), 'radial_velocity', 'radial_velocity_error', u.kms),
		oneStar ? bounded(ps, m.star_row_distance_photometric(), 'distance_gspphot', u.ly, PC_LY) : null
	];
	const positionSection = {
		key: 'position',
		title: m.star_section_position(),
		rows: rows(position)
	};
	if (!oneStar) {
		return [
			positionSection,
			{
				key: 'brightness',
				title: m.star_section_brightness(),
				rows: rows([...magnitudeRows(ps), variabilityRow(ps)])
			}
		];
	}

	// TODO: Replace this precedence when the export supplies one canonical stellar fit.
	const photometricFit = flameRows(ps, u, '');
	const spectroscopicFit = flameRows(ps, u, '_spec');
	const fitted = (quantity: keyof FlameRows) =>
		photometricFit[quantity] ?? spectroscopicFit[quantity];

	const classification = rows([
		row(m.star_stat_spectral_type(), spType),
		fitted('stage'),
		fitted('age') ?? hostAgeRow(ps.number('host_age')),
		variabilityRow(ps)
	]);

	const metallicity = metallicityRows(ps, orbit, u.dex);
	const atmosphere = rows([
		...metallicity,
		metallicity.length === 0 ? hostMetallicityRow(ps.number('host_metallicity')) : null
	]);

	const surface = rows([
		diameterRow(radius, ps, ps.number('host_radius_error')),
		gravityRow(ps.number('logg'), ps.number('logg_lower'), ps.number('logg_upper')),
		luminosityRow(ps),
		...magnitudeRows(ps),
		fitted('redshift'),
		measured(ps, m.star_row_line_broadening(), 'vbroad', 'vbroad_error', u.kms)
	]);

	return [
		{ key: 'classification', title: m.classification(), rows: classification },
		{ key: 'atmosphere', title: m.atmosphere(), rows: atmosphere },
		{ key: 'surface', title: m.surface(), rows: surface, temperature: teffScale(ps) },
		{ key: 'interior', title: m.interior(), ...interiorSection(ps, radius, structure) },
		positionSection
	];
}
