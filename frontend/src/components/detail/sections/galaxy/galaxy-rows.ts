/**
 * What the panel of a galaxy shows: its Redshift row, the facts of its object
 * entry, and what the catalogue holds of it. The works behind the values are
 * listed in the sources footer. A value that the export works out is marked as
 * an estimate.
 */

import * as m from '$lib/paraglide/messages.js';
import type {
	BoundedValue,
	CatalogueCounts,
	GalaxyGroup,
	GalaxyRow
} from '$lib/fetch/extrasolar/galaxies';
import {
	CAT_PLANETARY_SYSTEMS,
	CAT_SOLAR_SYSTEM,
	CAT_STARS,
	CAT_STAR_SYSTEMS
} from '$lib/fetch/groups/registry';
import type {
	EntityRef,
	GalaxyFact,
	GlobalObjectData,
	ValueReference
} from '$lib/fetch/objects/object-data';
import { ltrIsolate } from '$lib/format/bidi';
import {
	compactParts,
	formatAtLeast,
	formatMeasuredQuantity,
	formatNumber,
	formatSpan,
	fractionDigits,
	isolatedQuantity,
	powerOfTen,
	scientificNotation,
	sigFigures,
	type Parts
} from '$lib/format/quantities';
import { formatDeclination, formatRightAscension, withBounds } from '$lib/format/star';
import type { Stat } from '../kit/StatCard.svelte';
import {
	PC_LY,
	epochLabel,
	rows,
	units,
	type StarRowEntry,
	type StarSection
} from '../star/star-rows';

/** The Redshift row places a galaxy at J2016.0. */
const REDSHIFT_EPOCH = 2016;

/** Significant figures of a power of ten that has no bounds. */
const POWER_DIGITS = 3;

/** What the panel reads of a galaxy's object entry. */
export type GalaxyEntry = Pick<GlobalObjectData, 'references' | 'facts'>;

/** The pages that hold what is inside the galaxy of the Sun. */
export const HOME_GALAXY_TILES = [
	CAT_SOLAR_SYSTEM,
	CAT_STARS,
	CAT_STAR_SYSTEMS,
	CAT_PLANETARY_SYSTEMS
];

/** How a quantity is written: one figure of it, and a value with its bounds. */
interface Quantity {
	figure(value: number): Parts;
	reading(value: BoundedValue): string;
}

/** A product or a difference of published figures, without its float residue. */
function exact(value: number): number {
	return Number(value.toPrecision(12));
}

/** A value at the decimals that its paper prints, in the paper's unit. With
 *  `power`, as multiples of the power of ten of the value. */
function published(unit: string, power = false): Quantity {
	const figure = (value: number): Parts => ({
		value: power ? scientificNotation(value, POWER_DIGITS) : sigFigures(value),
		unit
	});
	return {
		figure,
		reading: ({ value, lower, upper }) => {
			if (lower === null || upper === null) return isolatedQuantity(figure(value));
			const exponent = power ? powerOfTen(value, POWER_DIGITS) : undefined;
			const scale = 10 ** -(exponent ?? 0);
			const upperError = exact(upper - value);
			const lowerError = exact(value - lower);
			const decimals = [value, upperError, lowerError].map((n) => fractionDigits(exact(n * scale)));
			return formatMeasuredQuantity({
				value,
				upperError,
				lowerError,
				unit,
				power: exponent,
				publishedDecimals: Math.max(...decimals)
			});
		}
	};
}

/** A length that its paper gives in parsecs, in light years. */
function lightYears(): Quantity {
	const { ly } = units();
	const figure = (pc: number): Parts => ({ value: sigFigures(pc * PC_LY), unit: ly });
	return {
		figure,
		reading: ({ value, lower, upper }) =>
			lower === null || upper === null
				? isolatedQuantity(figure(value))
				: withBounds(value * PC_LY, lower * PC_LY, upper * PC_LY, ly, true)
	};
}

/** A number of objects, written out. */
function count(): Quantity {
	return {
		figure: (value) => ({ value: formatNumber(value), unit: '' }),
		reading: (value) =>
			value.lower === null || value.upper === null
				? formatNumber(value.value)
				: published('').reading(value)
	};
}

/** A number of objects too large to write out: "100B". */
function compactCount(): Quantity {
	return { figure: compactParts, reading: ({ value }) => isolatedQuantity(compactParts(value)) };
}

/** The value of a fact: a value with its bounds, a range, or a lower limit. */
function factValue(fact: GalaxyFact, quantity: Quantity): string | null {
	const { value, lower, upper } = fact;
	if (value !== undefined) {
		return quantity.reading({ value, lower: lower ?? null, upper: upper ?? null });
	}
	if (lower === undefined) return null;
	if (upper === undefined) return formatAtLeast(isolatedQuantity(quantity.figure(lower)));
	return formatSpan(quantity.figure(lower), quantity.figure(upper));
}

interface FactRow {
	name: string;
	label: () => string;
	quantity: () => Quantity;
}

const solarMass = () => published(m.symbol_solar_mass(), true);
const perStar = () => published('');

/** The facts of each section, in row order. A fact that the entry lacks has no row. */
const FACT_ROWS: Record<string, FactRow[]> = {
	classification: [
		{ name: 'age', label: m.star_row_age, quantity: () => published(units().gigayear) }
	],
	structure: [
		{ name: 'half_light_radius', label: m.galaxy_row_half_light_radius, quantity: lightYears },
		{ name: 'scale_length', label: m.galaxy_row_scale_length, quantity: lightYears },
		{
			name: 'thin_disc_scale_height',
			label: m.galaxy_row_thin_disc_scale_height,
			quantity: lightYears
		},
		{
			name: 'thick_disc_scale_height',
			label: m.galaxy_row_thick_disc_scale_height,
			quantity: lightYears
		},
		{ name: 'disc_radius', label: m.galaxy_row_disc_radius, quantity: lightYears },
		{ name: 'bar_half_length', label: m.galaxy_row_bar_half_length, quantity: lightYears }
	],
	mass: [
		{ name: 'stellar_halo_mass', label: m.galaxy_row_stellar_halo_mass, quantity: solarMass },
		{ name: 'black_hole_mass', label: m.galaxy_row_black_hole_mass, quantity: solarMass }
	],
	rotation: [
		{
			name: 'circular_speed',
			label: m.galaxy_row_circular_speed,
			quantity: () => published(units().kms)
		},
		{
			name: 'orbital_period',
			label: m.galaxy_row_orbital_period,
			quantity: () => published(m.symbol_megaannum())
		}
	],
	stars: [{ name: 'star_count', label: m.group_stat_stars, quantity: compactCount }],
	population: [
		{
			name: 'supernova_rate',
			label: m.galaxy_row_supernova_rate,
			quantity: () => published(m.galaxy_unit_per_century())
		},
		{ name: 'planets_per_star', label: m.galaxy_row_planets_per_star, quantity: perStar },
		{
			name: 'free_floating_planets_per_star',
			label: m.galaxy_row_free_floating_planets_per_star,
			quantity: perStar
		},
		{ name: 'planet_count', label: m.group_stat_planets, quantity: compactCount }
	],
	companions: [
		{ name: 'globular_clusters', label: m.galaxy_row_globular_clusters, quantity: count },
		{ name: 'satellite_galaxies', label: m.galaxy_row_satellite_galaxies, quantity: count }
	]
};

/** A row and the works that it cites. */
interface CitedRow {
	row: StarRowEntry;
	works: readonly ValueReference[];
}

function factRow(spec: FactRow, entry: GalaxyEntry | null): CitedRow | null {
	const fact = entry?.facts?.[spec.name];
	const value = fact && factValue(fact, spec.quantity());
	if (!fact || !value) return null;
	return {
		row: {
			label: spec.label(),
			value,
			note: fact.estimate ? m.exoplanet_estimated() : undefined
		},
		works: fact.references
	};
}

function factRows(section: string, entry: GalaxyEntry | null): (CitedRow | null)[] {
	return FACT_ROWS[section].map((spec) => factRow(spec, entry));
}

/** A row of a value of the Redshift row, with the works of its column group. */
function groupRow(
	label: string,
	value: string | null,
	group: GalaxyGroup,
	entry: GalaxyEntry | null
): CitedRow | null {
	if (value === null) return null;
	const works = entry?.references?.[group] ?? [];
	return { row: { label, value }, works };
}

function reading(value: BoundedValue | null, quantity: Quantity): string | null {
	return value && quantity.reading(value);
}

interface CitedSection {
	key: string;
	title: string;
	rows: (CitedRow | null)[];
}

function citedSections(row: GalaxyRow | null, entry: GalaxyEntry | null): CitedSection[] {
	const type = row?.morphologicalType;
	const { ra, dec } = row ?? { ra: null, dec: null };
	const place = ra !== null && dec !== null;
	const rate = published(m.symbol_solar_mass_per_year());
	return [
		{
			key: 'classification',
			title: m.classification(),
			rows: [
				groupRow(m.galaxy_row_morphology(), type ? ltrIsolate(type) : null, 'morphology', entry),
				...factRows('classification', entry)
			]
		},
		{ key: 'structure', title: m.tab_structure(), rows: factRows('structure', entry) },
		{
			key: 'mass',
			title: m.star_stat_mass(),
			rows: [
				groupRow(
					m.galaxy_row_total_mass(),
					reading(row?.totalMass ?? null, solarMass()),
					'total_mass',
					entry
				),
				groupRow(
					m.galaxy_row_stellar_mass(),
					reading(row?.stellarMass ?? null, solarMass()),
					'stellar_mass',
					entry
				),
				...factRows('mass', entry)
			]
		},
		{ key: 'rotation', title: m.rotation(), rows: factRows('rotation', entry) },
		{
			key: 'population',
			title: m.galaxy_section_population(),
			rows: [
				...factRows('stars', entry),
				groupRow(
					m.galaxy_row_star_formation_rate(),
					reading(row?.starFormationRate ?? null, rate),
					'star_formation_rate',
					entry
				),
				...factRows('population', entry)
			]
		},
		{
			key: 'companions',
			title: m.galaxy_section_companions(),
			rows: factRows('companions', entry)
		},
		{
			key: 'position',
			title: m.star_section_position(),
			rows: [
				groupRow(
					m.star_row_ra(),
					place ? formatRightAscension(ra!, dec!, null) : null,
					'position',
					entry
				),
				groupRow(m.star_row_dec(), place ? formatDeclination(dec!, null) : null, 'position', entry),
				place
					? { row: { label: m.orbit_epoch(), value: epochLabel(REDSHIFT_EPOCH) }, works: [] }
					: null,
				groupRow(
					m.galaxy_row_centre_distance(),
					reading(row?.distance ?? null, lightYears()),
					'distance',
					entry
				)
			]
		}
	];
}

function present(entries: (CitedRow | null)[]): CitedRow[] {
	return entries.filter((entry): entry is CitedRow => entry !== null);
}

/** What the catalogue holds, which is not what the galaxy holds. */
function catalogueSection(counts: CatalogueCounts): StarSection {
	const row = (label: string, value: number | null): StarRowEntry | null =>
		value === null ? null : { label, value: formatNumber(value) };
	return {
		key: 'catalogue',
		title: m.galaxy_section_catalogue(),
		rows: rows([
			row(m.group_stat_stars(), counts.stars),
			row(m.about_data_kind_star_systems(), counts.starSystems),
			row(m.group_stat_planets(), counts.planets)
		])
	};
}

/** The sections of a galaxy's panel, in order; an empty one is left out.
 *  `counts` is what the catalogue holds of the galaxy; null for a galaxy whose
 *  objects the catalogue does not hold. `partOf` is Wikidata's "part of": the
 *  groups of the galaxy, which say what it is. */
export function galaxySections(
	row: GalaxyRow | null,
	entry: GalaxyEntry | null,
	counts: CatalogueCounts | null = null,
	partOf: readonly EntityRef[] = []
): StarSection[] {
	const sections: StarSection[] = citedSections(row, entry).map(({ key, title, rows }) => ({
		key,
		title,
		rows: present(rows).map((cited) => cited.row)
	}));
	if (partOf.length > 0) {
		const groups = { label: m.property_name_part_of(), value: '', entities: [...partOf] };
		sections.find((section) => section.key === 'classification')?.rows.push(groups);
	}
	if (counts) sections.push(catalogueSection(counts));
	return sections.filter((section) => section.rows.length > 0);
}

/** The works that the panel cites, each once, in panel order. */
export function galaxyWorks(row: GalaxyRow | null, entry: GalaxyEntry | null): ValueReference[] {
	const works = citedSections(row, entry).flatMap(({ rows }) =>
		present(rows).flatMap((cited) => cited.works)
	);
	return [...new Map(works.map((work) => [work.url, work])).values()];
}

/** The width of the disc: twice its radius, a limit when the radius is one. */
function discDiameter(radius: GalaxyFact): string | null {
	const { figure } = lightYears();
	if (radius.value !== undefined) return isolatedQuantity(figure(2 * radius.value));
	if (radius.lower === undefined || radius.upper !== undefined) return null;
	return formatAtLeast(isolatedQuantity(figure(2 * radius.lower)));
}

/** The cards, one row: how many stars, how wide, its type. */
export function galaxyStats(row: GalaxyRow | null, entry: GalaxyEntry | null): Stat[][] {
	const stars = entry?.facts?.star_count;
	const count = stars && factValue(stars, compactCount());
	const radius = entry?.facts?.disc_radius;
	const diameter = radius && discDiameter(radius);
	const type = row?.morphologicalType;
	const cards: (Stat | null)[] = [
		stars && count
			? {
					label: m.group_stat_stars(),
					value: count,
					note: stars.estimate ? m.exoplanet_estimated() : undefined
				}
			: null,
		diameter ? { label: m.diameter(), value: diameter } : null,
		type ? { label: m.galaxy_stat_type(), value: ltrIsolate(type) } : null
	];
	const shown = cards.filter((card): card is Stat => card !== null);
	return shown.length ? [shown] : [];
}
