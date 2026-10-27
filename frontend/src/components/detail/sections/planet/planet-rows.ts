/**
 * What a planet's panel shows, from its record in the system file: the badges,
 * the stat cards and the sections of rows. A value shows at the precision of
 * its error, or at the digits the catalogue gives. A value that is assumed,
 * estimated, computed or a limit says so.
 */

import * as m from '$lib/paraglide/messages.js';
import { getLocale } from '$lib/paraglide/runtime.js';
import type { Planet } from '$lib/fetch/extrasolar/planets';
import {
	errorDecimals,
	formatBound,
	formatLowerBound,
	formatMeasuredQuantity,
	formatUnit,
	fractionDigits,
	joinParts,
	scientificNotation,
	sigFigures
} from '$lib/format/quantities';
import { formatTemperature, formatTemperatureRange } from '$lib/format/temperature';
import { formatJulianDate } from '$lib/format/date';
import { ltrIsolate } from '$lib/format/bidi';
import { starSourceName } from '$lib/credits/star-sources';
import type { PlanetAnchor } from '$lib/types/objects';
import type { Stat } from '../kit/StatCard.svelte';
import { AU_KM, JUPITER_RADIUS_KM } from '$lib/math/units';
import { SECONDS_PER_DAY } from '$lib/time/jd';

/** Earth masses in one Jupiter mass (IAU nominal GM ratio). */
export const EARTH_MASSES_PER_JUPITER = 317.828;
/** Under this mass (MJ) a planet reads in Earth units: Neptune is 0.054 MJ. */
const EARTH_SCALE_MASS = 0.1;
/** A card shows a period of at least this many days in years. */
const PERIOD_YEARS_FROM = 1000;
const DAYS_PER_YEAR = 365.25;
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
	unit: string;
	/** Binds to the digits with no space, as degrees do. */
	tight?: boolean;
}

const NO_UNIT: Unit = { unit: '' };

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
	const out = formatMeasuredQuantity({
		value: raw * scale,
		upperError: up === null ? null : up * scale,
		lowerError: low === null ? null : low * scale,
		unit: unit.unit,
		tight: unit.tight,
		rawValue: raw,
		maxSignificantDigits: digits,
		publishedDecimals: published,
		roundLargeErrors: scale !== 1
	});
	return bounded(planet, name, out);
}

/** An upper ('<') or lower ('>') limit in place of a value. */
function limitOn(side: '<' | '>' | '' | null, out: string): string {
	if (side === '<') return formatBound(out);
	if (side === '>') return formatLowerBound(out);
	return out;
}

function bounded(planet: Planet, name: string, out: string): string {
	const side = (['<', '>'] as const).find((s) => planet.limits.includes(`${name}${s}`)) ?? '';
	return limitOn(side, out);
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
		degree: { unit: m.symbol_degree(), tight: true },
		au: { unit: formatUnit('astronomical_unit', true) },
		day: { unit: daySymbol() },
		jupiterMass: { unit: m.exoplanet_symbol_jupiter_mass() },
		earthMass: { unit: m.exoplanet_symbol_earth_mass() },
		km: { unit: formatUnit('kilometre', true) },
		earthFlux: { unit: m.exoplanet_symbol_earth_flux() },
		density: { unit: formatUnit('gram_per_cubic_centimetre', true) }
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
	return joinParts({ value: sigFigures(days, ROUNDED), unit: daySymbol() });
}

/** Whether the planet's mass reads more naturally in Earth masses. */
export function earthScale(planet: Planet): boolean {
	const mass = num(planet, 'mass');
	return mass !== null && mass < EARTH_SCALE_MASS;
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

/** The header badge names the object's class. */
export function planetBadges(planet: Planet): string[] {
	return [planetClassLabel(planet.class)].filter(Boolean);
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

/** A mass in the planet's scale, with the other unit beside it. */
function scaledMass(planet: Planet, digits?: number): { value: string; other: string } | null {
	const raw = num(planet, 'mass');
	if (raw === null) return null;
	const u = units();
	const earth = earthScale(planet);
	const factor = EARTH_MASSES_PER_JUPITER;
	const jupiterUnit = u.jupiterMass;
	const earthUnit = u.earthMass;
	const [unit, scale, otherUnit, otherScale] = earth
		? [earthUnit, factor, jupiterUnit, 1]
		: [jupiterUnit, 1, earthUnit, factor];
	if (digits !== undefined) {
		return {
			value: bounded(
				planet,
				'mass',
				joinParts({ value: sigFigures(raw * scale, digits), ...unit })
			),
			other: bounded(
				planet,
				'mass',
				joinParts({ value: sigFigures(raw * otherScale, digits), ...otherUnit })
			)
		};
	}
	return {
		value: measured(planet, 'mass', unit, scale)!,
		other: measured(planet, 'mass', otherUnit, otherScale)!
	};
}

/** A radius in km, as the Solar System's sizes read, at the figures the
 *  catalogue gives in Jupiter radii. */
function radiusKm(planet: Planet, digits?: number): string | null {
	const raw = num(planet, 'radius');
	if (raw === null) return null;
	const unit = units().km;
	if (digits === undefined) return measured(planet, 'radius', unit, JUPITER_RADIUS_KM);
	return bounded(
		planet,
		'radius',
		joinParts({ value: sigFigures(raw * JUPITER_RADIUS_KM, digits), ...unit })
	);
}

/** Ramanujan's ellipse circumference, as a ratio to its semi-major axis. */
function ellipseCircumferenceRatio(eccentricity: number): number {
	const minorRatio = Math.sqrt(1 - eccentricity ** 2);
	const h = ((1 - minorRatio) / (1 + minorRatio)) ** 2;
	return Math.PI * (1 + minorRatio) * (1 + (3 * h) / (10 + Math.sqrt(4 - 3 * h)));
}

/** How the mean orbital speed goes with each value it comes from. */
const SPEED_GROWS_WITH: [name: string, grows: boolean][] = [
	['semi_major_axis', true],
	['period', false],
	['eccentricity', false]
];

/** The side a limit on a value the speed comes from bounds the speed on: '<'
 *  at most, '>' at least, '' none. Null where two limits pull opposite ways. */
function speedBound(planet: Planet): '<' | '>' | '' | null {
	const sides = new Set<'<' | '>'>();
	for (const [name, grows] of SPEED_GROWS_WITH) {
		for (const side of ['<', '>'] as const) {
			if (planet.limits.includes(`${name}${side}`)) sides.add(grows === (side === '<') ? '<' : '>');
		}
	}
	if (sides.size > 1) return null;
	return [...sides][0] ?? '';
}

/** The three most useful available facts. */
export function planetStats(planet: Planet): Stat[][] {
	const u = units();
	const mass = scaledMass(planet, ROUNDED);
	const radius = radiusKm(planet, ROUNDED);
	const period = num(planet, 'period');
	const a = num(planet, 'semi_major_axis');
	const eccentricity = num(planet, 'eccentricity');
	const speedSide = speedBound(planet);
	const orbitalSpeed =
		speedSide !== null &&
		period !== null &&
		period > 0 &&
		a !== null &&
		a > 0 &&
		eccentricity !== null &&
		eccentricity >= 0 &&
		eccentricity < 1
			? (ellipseCircumferenceRatio(eccentricity) * a * AU_KM) / (period * SECONDS_PER_DAY)
			: null;
	const preferred: (Stat | null)[] = [
		radius
			? {
					label: m.exoplanet_radius(),
					value: radius,
					note: qualifier(planet, 'radius')
				}
			: mass
				? {
						label: m.exoplanet_mass(),
						value: mass.value,
						note: massKindNote(planet),
						tooltip: mass.other
					}
				: null,
		orbitalSpeed !== null
			? {
					label: m.exoplanet_mean_orbital_speed(),
					value: limitOn(
						speedSide,
						joinParts({
							value: sigFigures(orbitalSpeed, ROUNDED),
							unit: formatUnit('kilometre_per_second', true)
						})
					),
					note: m.exoplanet_computed()
				}
			: null,
		planet.status && planet.status !== 'confirmed'
			? { label: m.exoplanet_row_status(), value: statusLabel(planet.status)! }
			: null,
		a !== null
			? {
					label: m.exoplanet_stat_distance(),
					value: bounded(
						planet,
						'semi_major_axis',
						joinParts({ value: sigFigures(a, ROUNDED), ...u.au })
					),
					note: qualifier(planet, 'semi_major_axis')
				}
			: null
	];
	const fallback: (Stat | null)[] = [
		planet.class
			? {
					label: m.exoplanet_row_class(),
					value: planetClassLabel(planet.class),
					note: planet.class_basis
						? (BASIS_LABELS[planet.class_basis]?.() ?? planet.class_basis)
						: undefined
				}
			: null,
		period !== null
			? {
					label: m.orbital_period(),
					value: bounded(
						planet,
						'period',
						period >= PERIOD_YEARS_FROM
							? joinParts({
									value: sigFigures(period / DAYS_PER_YEAR, ROUNDED),
									unit: durationSymbol('year')
								})
							: formatDays(period)
					),
					note: qualifier(planet, 'period')
				}
			: null
	];
	const cards = [...preferred, ...fallback]
		.filter((card): card is Stat => card !== null)
		.slice(0, 3);
	return cards.length ? [cards] : [];
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

function list(items: string[]): string | null {
	if (items.length === 0) return null;
	return new Intl.ListFormat(getLocale(), { type: 'conjunction' }).format(items);
}

/** A catalogue's name of the planet, or an id that names nothing for a reader. */
function catalogueRow(planet: Planet, catalogue: string, label: string): PlanetRow | null {
	const id = planet.cross_ids.find((x) => x.catalogue === catalogue)?.catalogue_id;
	if (!id) return null;
	return { label, value: id, labelIsName: true };
}

/** Catalogue identifiers shown with the object's other links. */
export function planetIdentifiers(planet: Planet): PlanetRow[] {
	// The archive's internal id is a number such as `3.11922`; its overview
	// page takes the published designation instead.
	const archive = planet.cross_ids.some((x) => x.catalogue === ARCHIVE) ? planet.designation : null;
	return rows([
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
		catalogueRow(planet, 'open-exoplanet-catalogue', starSourceName('open-exoplanet-catalogue'))
	]);
}

/** Names not already shown as the planet's name or an identifier. */
export function planetAliases(planet: Planet): string[] {
	const shown = new Set([
		planet.name,
		planet.designation,
		...planet.cross_ids.map((x) => x.catalogue_id)
	]);
	return planet.aliases.filter((alias) => !shown.has(alias));
}

/** The sections of rows, in panel order; an empty section is left out. */
export function planetSections(anchor: PlanetAnchor): PlanetSection[] {
	const { planet } = anchor;
	const u = units();

	// TODO: Revisit time systems and map-fit caveats when the export owns their presentation.
	const orbit = rows([
		valueRow(planet, m.orbital_period(), 'period', u.day),
		valueRow(planet, m.eccentricity(), 'eccentricity'),
		valueRow(planet, m.inclination(), 'inclination', u.degree),
		valueRow(planet, m.semi_major_axis(), 'semi_major_axis', u.au),
		valueRow(planet, m.exoplanet_row_omega(), 'omega', u.degree),
		valueRow(planet, m.exoplanet_row_node(), 'node', u.degree),
		valueRow(planet, m.exoplanet_row_node_inclination(), 'node_inclination', u.degree),
		timeRow(
			m.exoplanet_row_periastron_time(),
			julian(planet, 'periastron_time', qualifier(planet, 'periastron_time'))
		),
		timeRow(m.exoplanet_row_transit_time(), julian(planet, 'transit_time'))
	]);

	const mass = scaledMass(planet);
	const radius = radiusKm(planet);
	const physical = rows([
		mass
			? {
					label: m.exoplanet_mass(),
					value: mass.value,
					note: massKindNote(planet),
					tooltip: mass.other
				}
			: null,
		num(planet, 'mass') === null && planet.mass_ratio !== null
			? row(m.exoplanet_row_mass_ratio(), scientificNotation(planet.mass_ratio, 2))
			: null,
		radius
			? {
					label: m.exoplanet_radius(),
					value: radius,
					note: qualifier(planet, 'radius')
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

	return [
		{ key: 'physical', title: m.exoplanet_section_physical(), rows: physical },
		{ key: 'atmosphere', title: m.atmosphere(), rows: atmosphere },
		{ key: 'orbit', title: m.orbital_elements(), rows: orbit },
		{ key: 'discovery', title: m.discovery(), rows: discovery }
	].filter((section) => section.rows.length > 0);
}
