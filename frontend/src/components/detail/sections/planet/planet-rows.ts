/**
 * What a planet's panel shows, from its record in the system file: the badges,
 * the stat cards and the sections of rows. A value shows at the precision of
 * its error, or at the digits the catalogue gives. A value that is assumed,
 * estimated, computed or a limit says so, and so does a planet whose drawn
 * orbit or place on it is not as published.
 */

import * as m from '$lib/paraglide/messages.js';
import { getLocale } from '$lib/paraglide/runtime.js';
import type { Planet, PlanetHost } from '$lib/fetch/extrasolar/planets';
import { extrasolarObjectId } from '$lib/fetch/extrasolar/ids';
import { errorDecimals, fixed } from '$lib/format/star';
import {
	formatBound,
	formatLowerBound,
	formatUnit,
	scientificNotation,
	sigFigures
} from '$lib/format/quantities';
import { formatTemperature, formatTemperatureRange } from '$lib/format/temperature';
import { formatJulianDate } from '$lib/format/date';
import { ltrIsolate } from '$lib/format/bidi';
import { starSourceName } from '$lib/credits/star-sources';
import type { LinkTarget } from '$lib/state/focus-link';
import type { PlanetAnchor } from '$lib/types/objects';
import type { Stat } from '../kit/StatCard.svelte';

/** Earth masses in one Jupiter mass (IAU nominal GM ratio). */
export const EARTH_MASSES_PER_JUPITER = 317.828;
/** Earth radii in one Jupiter radius (equatorial, 71,492 / 6,378.1 km). */
export const EARTH_RADII_PER_JUPITER = 11.209;
/** Under this mass (MJ) a planet reads in Earth units: Neptune is 0.054 MJ. */
const EARTH_SCALE_MASS = 0.1;
/** With no mass, under this radius (RJ): Neptune is 0.35 RJ. */
const EARTH_SCALE_RADIUS = 0.5;
/** A card shows a period of at least this many days in years. */
const PERIOD_YEARS_FROM = 1000;
const DAYS_PER_YEAR = 365.25;
/** Bounds this close to symmetric read as one ± error. */
const SYMMETRIC = 0.1;
/** Significant figures of a card, and of a computed or estimated value. */
const ROUNDED = 3;
/** Significant figures of an assumed value. The decimals of a default node mean nothing. */
const ASSUMED = 4;
/** At most this many significant figures of a published value. */
const PUBLISHED_MAX = 9;

export interface PlanetRow {
	label: string;
	value: string;
	/** What this value is: assumed, estimated, computed. */
	note?: string;
	/** What it comes to in another unit. */
	tooltip?: string;
	/** Where the value leads, off the site. */
	href?: string;
	/** The page of the map it leads to. */
	target?: LinkTarget;
	/** The label is a catalogue's name, kept as written. */
	labelIsName?: boolean;
}

export interface PlanetSection {
	key: string;
	title: string;
	rows: PlanetRow[];
}

const ARCHIVE = 'nasa-exoplanet-archive';
const ARCHIVE_OVERVIEW = 'https://exoplanetarchive.ipac.caltech.edu/overview/';

/** The archive's page of a system, by the name of one of its stars or planets. */
export function archiveOverview(name: string): string {
	return `${ARCHIVE_OVERVIEW}${encodeURIComponent(name)}`;
}

interface Unit {
	symbol: string;
	/** Binds to the digits with no space, as degrees do. */
	tight?: boolean;
}

const NO_UNIT: Unit = { symbol: '' };

function withUnit(text: string, unit: Unit): string {
	if (!unit.symbol) return text;
	return unit.tight ? `${text}${unit.symbol}` : `${text}\u00a0${unit.symbol}`;
}

/** Significant figures of a published decimal: "0.0033194" has 5. */
function publishedDigits(value: number): number {
	const mantissa = Math.abs(value).toExponential().split('e')[0];
	return Math.max(1, mantissa.replace('.', '').replace(/0+$/, '').length);
}

/** Fraction digits of a published decimal: "0.040" was written 0.04, so 2. */
function fractionDigits(value: number): number {
	const [mantissa, exponent] = Math.abs(value).toExponential().split('e');
	const digits = (mantissa.split('.')[1] ?? '').replace(/0+$/, '').length;
	return Math.max(0, digits - Number(exponent));
}

function significant(value: number, digits: number): string {
	return new Intl.NumberFormat(getLocale(), { maximumSignificantDigits: digits }).format(value);
}

/**
 * `value` and its errors: "11.18465 ± 0.00053 d" where they are as good as
 * symmetric, "3.3° (1.0–5.1°)" where not. A wrap goes before the ±, so the ±
 * stays with its error. The error shows to two significant figures, but not
 * past the digits the catalogue gave when `published` names them. With no
 * error, the digits of the published `raw` value; `digits` caps them.
 */
function withErrors(
	value: number,
	upper: number | null,
	lower: number | null,
	unit: Unit,
	raw: number,
	digits = PUBLISHED_MAX,
	published: number | null = null
): string {
	const up = upper !== null && upper > 0 ? upper : null;
	const low = lower !== null && lower > 0 ? lower : null;
	if (up === null && low === null) {
		return withUnit(significant(value, Math.min(publishedDigits(raw), digits)), unit);
	}
	const hi = up ?? low!;
	const lo = low ?? up!;
	const half = (hi + lo) / 2;
	const decimals = (error: number) =>
		published === null ? errorDecimals(error) : Math.min(errorDecimals(error), published);
	if (Math.abs(hi - lo) <= SYMMETRIC * half) {
		const d = decimals(half);
		const v = fixed(value, d);
		const e = fixed(half, d);
		return ltrIsolate(
			unit.tight
				? `${withUnit(v, unit)} ±\u00a0${withUnit(e, unit)}`
				: `${v} ±\u00a0${withUnit(e, unit)}`
		);
	}
	const d = decimals(Math.min(hi, lo));
	const from = value - lo;
	const to = value + hi;
	// Spaced where an end is negative: "−0.18–−0.17" jams the dash against a sign.
	const separator = from < 0 || to < 0 ? ' – ' : '–';
	const span = withUnit(`${fixed(from, d)}${separator}${fixed(to, d)}`, unit);
	return ltrIsolate(`${withUnit(fixed(value, d), unit)} (${span})`);
}

/** A catalogue's value and its errors at the digits it gave them. */
export function catalogueQuantity(
	value: number,
	upper: number | null,
	lower: number | null,
	unit: string
): string {
	const published = Math.max(...[value, upper ?? 0, lower ?? 0].map(fractionDigits));
	return withErrors(value, upper, lower, { symbol: unit }, value, PUBLISHED_MAX, published);
}

function num(planet: Planet, name: string): number | null {
	const value = planet.values[name];
	return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function text(planet: Planet, name: string): string | null {
	const value = planet.values[name];
	return typeof value === 'string' && value ? value : null;
}

/** The significant figures a value without errors shows. */
function digitsOf(planet: Planet, name: string): number {
	if (planet.estimated.includes(name) || planet.computed.includes(name)) return ROUNDED;
	return planet.assumed.includes(name) ? ASSUMED : PUBLISHED_MAX;
}

/** A value of the record and its errors, `scale` times the published unit. */
function measured(planet: Planet, name: string, unit: Unit = NO_UNIT, scale = 1): string | null {
	const raw = num(planet, name);
	if (raw === null) return null;
	const up = num(planet, `${name}_error_upper`);
	const low = num(planet, `${name}_error_lower`);
	const digits = digitsOf(planet, name);
	// The catalogue's digits hold in its own unit only.
	const published = scale === 1 ? Math.max(...[raw, up ?? 0, low ?? 0].map(fractionDigits)) : null;
	const out = withErrors(
		raw * scale,
		up === null ? null : up * scale,
		low === null ? null : low * scale,
		unit,
		raw,
		digits,
		published
	);
	return bounded(planet, name, out);
}

/** An upper or lower limit in place of a value. */
function bounded(planet: Planet, name: string, out: string): string {
	if (planet.limits.includes(`${name}<`)) return formatBound(out);
	if (planet.limits.includes(`${name}>`)) return formatLowerBound(out);
	return out;
}

/** The word that says how a value was had, when it was not measured. */
function qualifier(planet: Planet, name: string): string | undefined {
	if (planet.assumed.includes(name)) return m.exoplanet_assumed();
	if (planet.estimated.includes(name)) return m.exoplanet_estimated();
	if (planet.computed.includes(name)) return m.exoplanet_computed();
	return undefined;
}

function row(
	label: string,
	value: string | null,
	extra: Omit<PlanetRow, 'label' | 'value'> = {}
): PlanetRow | null {
	return value ? { label, value, ...extra } : null;
}

/** A value row, with its qualifier. */
function valueRow(
	planet: Planet,
	label: string,
	name: string,
	unit: Unit = NO_UNIT,
	scale = 1
): PlanetRow | null {
	return row(label, measured(planet, name, unit, scale), { note: qualifier(planet, name) });
}

function rows(entries: (PlanetRow | null)[]): PlanetRow[] {
	return entries.filter((entry): entry is PlanetRow => entry !== null);
}

function units() {
	return {
		degree: { symbol: m.symbol_degree(), tight: true },
		au: { symbol: formatUnit('astronomical_unit', true) },
		day: { symbol: daySymbol() },
		jupiterMass: { symbol: m.exoplanet_symbol_jupiter_mass() },
		earthMass: { symbol: m.exoplanet_symbol_earth_mass() },
		jupiterRadius: { symbol: m.exoplanet_symbol_jupiter_radius() },
		earthRadius: { symbol: m.exoplanet_symbol_earth_radius() },
		solarMass: { symbol: m.exoplanet_symbol_solar_mass() },
		solarRadius: { symbol: m.exoplanet_symbol_solar_radius() },
		earthFlux: { symbol: m.exoplanet_symbol_earth_flux() },
		density: { symbol: formatUnit('gram_per_cubic_centimetre', true) },
		dex: { symbol: m.symbol_dex() },
		pc: { symbol: m.symbol_parsec() }
	} satisfies Record<string, Unit>;
}

/** The locale's short symbol for days, or for years. */
function durationSymbol(unit: 'day' | 'year'): string {
	return new Intl.NumberFormat(getLocale(), { style: 'unit', unit, unitDisplay: 'narrow' })
		.formatToParts(2)
		.filter((part) => part.type === 'unit')
		.map((part) => part.value)
		.join('')
		.trim();
}

function daySymbol(): string {
	return durationSymbol('day');
}

/** A period in days to three figures, as the cards and the planet lists write it. */
export function formatDays(days: number): string {
	return withUnit(sigFigures(days, ROUNDED), { symbol: daySymbol() });
}

/** Whether the planet reads in Earth masses and radii rather than Jupiter's. */
export function earthScale(planet: Planet): boolean {
	const mass = num(planet, 'mass');
	if (mass !== null) return mass < EARTH_SCALE_MASS;
	const radius = num(planet, 'radius');
	return radius !== null && radius < EARTH_SCALE_RADIUS;
}

const CLASS_LABELS: Record<string, () => string> = {
	planet: m.exoplanet_class_planet,
	'brown dwarf': m.exoplanet_class_brown_dwarf,
	'sub-brown dwarf': m.exoplanet_class_sub_brown_dwarf
};

const BASIS_LABELS: Record<string, () => string> = {
	'true mass': m.exoplanet_basis_true_mass,
	'minimum mass': m.exoplanet_basis_minimum_mass,
	'estimated mass': m.exoplanet_basis_estimated_mass,
	'no mass': m.exoplanet_basis_no_mass
};

/** A planet's class in words. */
export function planetClassLabel(cls: string | null): string {
	return (cls && CLASS_LABELS[cls]?.()) || (cls ?? '');
}

function statusLabel(status: string | null): string | null {
	if (status === 'confirmed') return m.exoplanet_status_confirmed();
	if (status === 'controversial') return m.exoplanet_status_controversial();
	return status;
}

/** The header badges: the class, and a controversial status. */
export function planetBadges(planet: Planet): string[] {
	const out = [planetClassLabel(planet.class)];
	if (planet.status === 'controversial') out.push(m.exoplanet_status_controversial());
	return out.filter(Boolean);
}

const METHOD_LABELS: Record<string, () => string> = {
	transit: m.exoplanet_method_transit,
	'radial velocity': m.exoplanet_method_radial_velocity,
	imaging: m.exoplanet_method_imaging,
	microlensing: m.exoplanet_method_microlensing,
	timing: m.exoplanet_method_timing,
	astrometry: m.exoplanet_method_astrometry,
	other: m.exoplanet_method_other,
	'transit timing variations': m.exoplanet_method_transit_timing,
	'eclipse timing variations': m.exoplanet_method_eclipse_timing,
	'orbital brightness modulation': m.exoplanet_method_brightness_modulation,
	'pulsar timing': m.exoplanet_method_pulsar_timing,
	'disk kinematics': m.exoplanet_method_disk_kinematics,
	'pulsation timing variations': m.exoplanet_method_pulsation_timing
};

/** A discovery method as the catalogues name it, in words. */
export function discoveryMethodLabel(method: string): string {
	return METHOD_LABELS[method.toLowerCase()]?.() ?? method;
}

/** The note on a mass: its kind, when it is not a true mass. */
function massKindNote(planet: Planet): string | undefined {
	const kind = text(planet, 'mass_kind');
	if (kind === 'minimum') return m.exoplanet_mass_minimum();
	if (kind === 'estimate') return m.exoplanet_mass_estimate();
	return undefined;
}

/** A mass or a radius in the planet's scale, with the other unit beside it. */
function scaled(
	planet: Planet,
	name: 'mass' | 'radius',
	digits?: number
): { value: string; other: string } | null {
	const raw = num(planet, name);
	if (raw === null) return null;
	const u = units();
	const earth = earthScale(planet);
	const factor = name === 'mass' ? EARTH_MASSES_PER_JUPITER : EARTH_RADII_PER_JUPITER;
	const jupiterUnit = name === 'mass' ? u.jupiterMass : u.jupiterRadius;
	const earthUnit = name === 'mass' ? u.earthMass : u.earthRadius;
	const [unit, scale, otherUnit, otherScale] = earth
		? [earthUnit, factor, jupiterUnit, 1]
		: [jupiterUnit, 1, earthUnit, factor];
	if (digits !== undefined) {
		return {
			value: bounded(planet, name, withUnit(sigFigures(raw * scale, digits), unit)),
			other: bounded(planet, name, withUnit(sigFigures(raw * otherScale, digits), otherUnit))
		};
	}
	return {
		value: measured(planet, name, unit, scale)!,
		other: measured(planet, name, otherUnit, otherScale)!
	};
}

function unknownCard(label: string): Stat {
	return { label, value: m.unknown() };
}

/** The stat cards, two to a row: mass, radius, period and the distance from
 *  the star. A value the record does not have reads as unknown. */
export function planetStats(planet: Planet): Stat[][] {
	const u = units();
	const mass = scaled(planet, 'mass', ROUNDED);
	const radius = scaled(planet, 'radius', ROUNDED);
	const period = num(planet, 'period');
	const a = num(planet, 'semi_major_axis');
	const cards: Stat[] = [
		mass
			? {
					label: m.exoplanet_mass(),
					value: mass.value,
					note: massKindNote(planet),
					tooltip: mass.other
				}
			: unknownCard(m.exoplanet_mass()),
		radius
			? {
					label: m.exoplanet_radius(),
					value: radius.value,
					note: qualifier(planet, 'radius'),
					tooltip: radius.other
				}
			: unknownCard(m.exoplanet_radius()),
		period !== null
			? {
					label: m.orbital_period(),
					value: bounded(
						planet,
						'period',
						period >= PERIOD_YEARS_FROM
							? withUnit(sigFigures(period / DAYS_PER_YEAR, ROUNDED), {
									symbol: durationSymbol('year')
								})
							: formatDays(period)
					),
					note: qualifier(planet, 'period')
				}
			: unknownCard(m.orbital_period()),
		a !== null
			? {
					label: m.exoplanet_stat_distance(),
					value: bounded(planet, 'semi_major_axis', withUnit(sigFigures(a, ROUNDED), u.au)),
					note: qualifier(planet, 'semi_major_axis')
				}
			: unknownCard(m.exoplanet_stat_distance())
	];
	return [cards.slice(0, 2), cards.slice(2, 4)];
}

/** "2457897.9 ± 0.3": a time as the catalogue gives it. Its date goes in the
 *  tooltip. */
function julian(planet: Planet, name: string, note?: string): Omit<PlanetRow, 'label'> | null {
	const jd = num(planet, name);
	if (jd === null) return null;
	const up = num(planet, `${name}_error_upper`);
	const low = num(planet, `${name}_error_lower`);
	const error = Math.max(up ?? 0, low ?? 0);
	const published = Math.max(fractionDigits(jd), fractionDigits(error));
	const decimals = error > 0 ? Math.min(errorDecimals(error), published) : published;
	const format = (v: number) =>
		new Intl.NumberFormat(getLocale(), {
			minimumFractionDigits: decimals,
			maximumFractionDigits: decimals,
			useGrouping: false
		}).format(v);
	const value = error > 0 ? `${format(jd)} ±\u00a0${format(error)}` : format(jd);
	return { value: ltrIsolate(value), tooltip: formatJulianDate(jd), note };
}

function timeRow(label: string, time: Omit<PlanetRow, 'label'> | null): PlanetRow | null {
	return time ? { label, ...time } : null;
}

/** A temperature (K) and the span of its errors, in the app's unit. */
function temperature(planet: Planet, name: string): string | null {
	const kelvin = num(planet, name);
	if (kelvin === null) return null;
	const value = formatTemperature({ value: kelvin, unit: 'kelvin' });
	const up = num(planet, `${name}_error_upper`);
	const low = num(planet, `${name}_error_lower`);
	if (!(up && up > 0) || !(low && low > 0)) return bounded(planet, name, value);
	const lowK = { value: kelvin - low, unit: 'kelvin' };
	const highK = { value: kelvin + up, unit: 'kelvin' };
	return bounded(planet, name, ltrIsolate(`${value} (${formatTemperatureRange(lowK, highK)})`));
}

const SUBSCRIPTS = '₀₁₂₃₄₅₆₇₈₉';

/** A formula with its counts set low: "H2O" reads "H₂O". */
function formula(molecule: string): string {
	return molecule.replace(/[0-9]/g, (d) => SUBSCRIPTS[Number(d)]);
}

/** Past this many characters a name may not fit the phone's value column. */
const WHOLE_NAME_MAX = 20;

/**
 * A name with no-break spaces, so a list of names wraps between them. A longer
 * name keeps its spaces: held whole, it would break mid-number in a narrow column.
 */
function wholeName(name: string): string {
	return name.length > WHOLE_NAME_MAX ? name : name.replace(/ /g, '\u00a0');
}

function list(items: string[]): string | null {
	if (items.length === 0) return null;
	return new Intl.ListFormat(getLocale(), { type: 'conjunction' }).format(items);
}

function binaryLabel(type: string | null): string | null {
	if (type === 'S-type') return m.exoplanet_binary_s();
	if (type === 'P-type') return m.exoplanet_binary_p();
	return type;
}

/** A catalogue's name of the planet, or an id that names nothing for a reader. */
function catalogueRow(planet: Planet, catalogue: string, label: string): PlanetRow | null {
	const id = planet.cross_ids.find((x) => x.catalogue === catalogue)?.catalogue_id;
	if (!id) return null;
	return { label, value: id, labelIsName: true };
}

/** The sections of rows, in panel order; an empty section is left out. */
export function planetSections(anchor: PlanetAnchor): PlanetSection[] {
	const { planet, hostRecord } = anchor;
	const u = units();
	const elements = planet.elements;

	const classification = rows([
		row(m.exoplanet_row_class(), planetClassLabel(planet.class)),
		row(
			m.exoplanet_row_class_basis(),
			planet.class_basis ? (BASIS_LABELS[planet.class_basis]?.() ?? planet.class_basis) : null
		),
		row(
			m.exoplanet_row_mass_ratio(),
			planet.mass_ratio === null ? null : scientificNotation(planet.mass_ratio, 2)
		),
		row(m.exoplanet_row_status(), statusLabel(planet.status))
	]);

	const phase = elements
		? elements.phase === 'transit'
			? m.exoplanet_phase_transit()
			: elements.phase === 'periastron'
				? m.exoplanet_phase_periastron()
				: m.unknown()
		: null;
	const drawn = !elements
		? m.exoplanet_drawn_none()
		: elements.replaced?.includes('eccentricity')
			? m.exoplanet_drawn_circle()
			: null;
	const orbit = rows([
		valueRow(planet, m.orbital_period(), 'period', u.day),
		valueRow(planet, m.semi_major_axis(), 'semi_major_axis', u.au),
		valueRow(planet, m.eccentricity(), 'eccentricity'),
		valueRow(planet, m.inclination(), 'inclination', u.degree),
		valueRow(planet, m.exoplanet_row_omega(), 'omega', u.degree),
		valueRow(planet, m.exoplanet_row_node(), 'node', u.degree),
		valueRow(planet, m.exoplanet_row_node_inclination(), 'node_inclination', u.degree),
		row(m.exoplanet_row_node_solution(), text(planet, 'node_solution')),
		timeRow(
			m.exoplanet_row_periastron_time(),
			julian(planet, 'periastron_time', qualifier(planet, 'periastron_time'))
		),
		timeRow(m.exoplanet_row_transit_time(), julian(planet, 'transit_time')),
		row(m.exoplanet_row_time_system(), text(planet, 'time_system')),
		row(m.exoplanet_row_phase(), phase),
		row(m.exoplanet_row_drawn(), drawn)
	]);

	const mass = scaled(planet, 'mass');
	const radius = scaled(planet, 'radius');
	const physical = rows([
		mass
			? {
					label: m.exoplanet_mass(),
					value: mass.value,
					note: massKindNote(planet),
					tooltip: mass.other
				}
			: null,
		radius
			? {
					label: m.exoplanet_radius(),
					value: radius.value,
					note: qualifier(planet, 'radius'),
					tooltip: radius.other
				}
			: null,
		valueRow(planet, m.exoplanet_row_density(), 'density', u.density),
		row(m.exoplanet_row_equilibrium_temperature(), temperature(planet, 'equilibrium_temperature'), {
			note: qualifier(planet, 'equilibrium_temperature')
		}),
		valueRow(planet, m.exoplanet_row_insolation(), 'insolation', u.earthFlux)
	]);

	const molecules = planet.values.molecules;
	const atmosphere = rows([
		row(m.exoplanet_row_molecules(), Array.isArray(molecules) ? list(molecules.map(formula)) : null)
	]);

	const method = text(planet, 'discovery_method');
	const year = num(planet, 'discovery_year');
	const discovery = rows([
		row(m.discovery_method(), method && discoveryMethodLabel(method)),
		row(m.exoplanet_row_discovery_year(), year === null ? null : String(year)),
		row(m.exoplanet_row_discovery_facility(), text(planet, 'discovery_facility'))
	]);

	const host = rows([hostLink(hostRecord), ...hostRows(planet, hostRecord, u)]);

	const shown = new Set([planet.name, planet.designation]);
	const catalogueNames = planet.cross_ids
		.filter((x) => x.catalogue !== ARCHIVE)
		.map((x) => x.catalogue_id);
	for (const name of catalogueNames) shown.add(name);
	// The archive's own id is a number such as `3.11922`; its name of the
	// planet is the designation, which its overview page takes.
	const archive = planet.cross_ids.some((x) => x.catalogue === ARCHIVE) ? planet.designation : null;
	const identifiers = rows([
		planet.name_source === 'iau-nameexoworlds' ? row(m.star_xid_iau(), planet.name) : null,
		row(m.exoplanet_row_designation(), planet.designation),
		archive
			? {
					label: starSourceName(ARCHIVE),
					value: archive,
					href: archiveOverview(archive),
					labelIsName: true
				}
			: null,
		catalogueRow(planet, 'exoplanet-eu', starSourceName('exoplanet-eu')),
		catalogueRow(planet, 'open-exoplanet-catalogue', starSourceName('open-exoplanet-catalogue')),
		row(
			m.exoplanet_row_aliases(),
			list(planet.aliases.filter((a) => !shown.has(a)).map(wholeName))
		),
		row(m.star_row_space_map_id(), `${planet.host}/b/${planet.number}`)
	]);

	return [
		{ key: 'classification', title: m.exoplanet_section_classification(), rows: classification },
		{ key: 'orbit', title: m.exoplanet_section_orbit(), rows: orbit },
		{ key: 'physical', title: m.exoplanet_section_physical(), rows: physical },
		{ key: 'atmosphere', title: m.atmosphere(), rows: atmosphere },
		{ key: 'discovery', title: m.discovery(), rows: discovery },
		{ key: 'host', title: m.exoplanet_section_host(), rows: host },
		{ key: 'identifiers', title: m.star_section_identifiers(), rows: identifiers },
		{ key: 'sources', title: m.exoplanet_section_sources(), rows: sourceRows(planet) }
	].filter((section) => section.rows.length > 0);
}

function hostLink(host: PlanetHost): PlanetRow {
	const name = host.name ?? String(host.id);
	return {
		label: m.exoplanet_row_host(),
		value: name,
		target: { id: extrasolarObjectId(host.id) }
	};
}

/** The star as the planet's catalogue fitted it, and where it is. */
function hostRows(
	planet: Planet,
	host: PlanetHost,
	u: ReturnType<typeof units>
): (PlanetRow | null)[] {
	const distance = host.distance === null ? null : withUnit(sigFigures(host.distance, 4), u.pc);
	return [
		row(m.star_row_distance(), distance, {
			note: host.placement === 'catalogue distance' ? m.exoplanet_distance_catalogue() : undefined
		}),
		valueRow(planet, m.exoplanet_mass(), 'star_mass', u.solarMass),
		valueRow(planet, m.exoplanet_radius(), 'star_radius', u.solarRadius),
		row(m.star_row_teff(), temperature(planet, 'star_teff')),
		valueRow(planet, m.exoplanet_row_metallicity(), 'star_metallicity', u.dex),
		row(m.exoplanet_row_binary(), binaryLabel(text(planet, 'binary_type')))
	];
}

/** The label of each group of values the record names a source for. */
function groupLabels(): Record<string, string> {
	return {
		status: m.exoplanet_row_status(),
		discovery: m.discovery(),
		orbit: m.exoplanet_section_orbit(),
		sky: m.exoplanet_source_sky(),
		mass: m.exoplanet_mass(),
		radius: m.exoplanet_radius(),
		physical: m.exoplanet_source_physical(),
		atmosphere: m.atmosphere(),
		stellar: m.exoplanet_source_stellar(),
		binary: m.exoplanet_row_binary()
	};
}

/** Where the name and each group of values come from. */
function sourceRows(planet: Planet): PlanetRow[] {
	const labels = groupLabels();
	const out: (PlanetRow | null)[] = [
		row(m.exoplanet_source_name(), planet.name_source && starSourceName(planet.name_source))
	];
	for (const [group, label] of Object.entries(labels)) {
		const source = planet.sources[group];
		if (source) out.push({ label, value: starSourceName(source) });
	}
	return rows(out);
}
