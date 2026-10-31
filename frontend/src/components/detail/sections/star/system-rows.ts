/**
 * What the panel of a star system's node or held star shows, from its System
 * row. A node has no one-star values: its cards count what it holds, and its
 * rows are what is true of its point. A value with a source says where it is
 * from on its tooltip.
 */

import * as m from '$lib/paraglide/messages.js';
import { starSourceName } from '$lib/credits/star-sources';
import { astrometricOrbit, type ExtrasolarRecord } from '$lib/fetch/extrasolar/lookup';
import type {
	HeldStarValues,
	PairOrbit,
	SystemCitation,
	SystemNode
} from '$lib/fetch/extrasolar/systems';
import type { EntityRef } from '$lib/fetch/objects/object-data';
import { ltrIsolate } from '$lib/format/bidi';
import { formatDeclination, formatRightAscension } from '$lib/format/star';
import { formatMass, massComparison, SOLAR_MASS_KG, sizeComparison } from '$lib/format/mass';
import { formatCompactKm } from '$lib/format/distance';
import { formatUnit, joinParts, sigFigures } from '$lib/format/quantities';
import { formatTemperature } from '$lib/format/temperature';
import { SOLAR_RADIUS_KM } from '$lib/math/units';
import { systemRows, type StarSystem, type SystemRow } from '$lib/state/star-system';
import type { Stat } from '../kit/StatCard.svelte';
import { formatJulianDay, formatPeriod } from '../planet/planet-rows';
import {
	PC_LY,
	POINT_SOURCE_SLUG,
	distanceStat,
	epochLabel,
	pointDistanceStat,
	row,
	rows,
	spectralType,
	starSections,
	units,
	type StarRowEntry,
	type StarSection
} from './star-rows';

/** The System row places a node at the J2016.0 place of its primary. */
const SYSTEM_EPOCH = 2016;

/** Significant figures of a published element. */
const ELEMENT = 6;
/** Of a semi-major axis, which a distance can scale from an angle. */
const AXIS = 5;
/** Of an assumed element. The decimals of a default node mean nothing. */
const ASSUMED = 4;
/** Of a computed element. */
const COMPUTED = 3;
/** Decimals of a Julian day: under a second. */
const JD_DECIMALS = 5;

/** Where a value is from: the work that its source cites, else the source. */
function sourceOf(
	source: string | null,
	references: readonly SystemCitation[]
): string | undefined {
	if (!source) return undefined;
	const short = references.find((work) => work.source === source)?.short;
	return `${m.source_prefix()} ${short ?? starSourceName(source)}`;
}

/** An object's link in a row. */
function objectRef(id: number, name: string): EntityRef {
	return { name, primary_type: 'x', primary_id: String(id) };
}

function rowDistanceStat(node: SystemNode): Stat | null {
	return node.distance === null ? null : distanceStat(node.distance);
}

function massCard(star: HeldStarValues): Stat | null {
	if (star.mass === null) return null;
	const kg = star.mass * SOLAR_MASS_KG;
	return { label: m.star_stat_mass(), value: formatMass(kg), tooltip: massComparison(kg) };
}

function diameterValue(radius: number): string {
	return formatCompactKm(2 * radius * SOLAR_RADIUS_KM);
}

function heldStarStats(node: SystemNode, star: HeldStarValues): (Stat | null)[] {
	const diameter =
		star.radius === null
			? null
			: {
					label: m.diameter(),
					value: diameterValue(star.radius),
					tooltip: sizeComparison(star.radius * SOLAR_RADIUS_KM)
				};
	const code = spectralType(star.spectralType);
	const nature =
		star.teff !== null
			? {
					label: m.star_stat_temperature(),
					value: formatTemperature({ value: star.teff, unit: 'kelvin' })
				}
			: code
				? { label: m.star_stat_spectral_type(), value: code }
				: null;
	return [diameter ?? massCard(star), rowDistanceStat(node), nature, diameter && massCard(star)];
}

function nodeStats(record: ExtrasolarRecord, node: SystemNode, planets: number): (Stat | null)[] {
	const ps = record.rows.get(POINT_SOURCE_SLUG);
	return [
		{ label: m.system_stars(), value: String(node.stars) },
		planets > 0 ? { label: m.exoplanet_strip_planets(), value: String(planets) } : null,
		(ps && pointDistanceStat(ps, astrometricOrbit(record))) ?? rowDistanceStat(node)
	];
}

/** The cards of a node, which holds `planets` planets, or of a held star. */
export function systemStats(record: ExtrasolarRecord, node: SystemNode, planets: number): Stat[][] {
	const cards = node.star ? heldStarStats(node, node.star) : nodeStats(record, node, planets);
	return [cards.filter((card): card is Stat => card !== null).slice(0, 3)];
}

function degrees(value: number, digits: number): string {
	return joinParts({ value: sigFigures(value, digits), unit: m.symbol_degree(), tight: true });
}

function arcseconds(value: number): string {
	return joinParts({ value: sigFigures(value), unit: m.symbol_arcsecond(), tight: true });
}

/** Joins the hints of one value. */
function hint(...parts: (string | null | undefined)[]): string | undefined {
	return parts.filter(Boolean).join(' · ') || undefined;
}

/** The element rows of a pair's orbit. An assumed or computed element says so. */
function orbitElements(orbit: PairOrbit): {
	period: StarRowEntry;
	axis: StarRowEntry;
	shape: StarRowEntry[];
} {
	const { references } = orbit;
	const assumed = (name: string) => orbit.assumed.includes(name);
	const computed = (name: string) => orbit.computed.includes(name);
	const note = (name: string) =>
		assumed(name) ? m.exoplanet_assumed() : computed(name) ? m.exoplanet_computed() : undefined;
	const digits = (name: string, published = ELEMENT) =>
		assumed(name) ? ASSUMED : computed(name) ? COMPUTED : published;
	const angle = (label: string, name: string, value: number, source: string | null) => ({
		label,
		value: degrees(value, digits(name)),
		note: note(name),
		tooltip: sourceOf(source, references)
	});
	const epoch = formatJulianDay(Number(orbit.periastronTime.toFixed(JD_DECIMALS)));
	const angular = orbit.semiMajorAxisArcsec;
	return {
		period: {
			label: m.orbital_period(),
			value: formatPeriod(orbit.period, digits('period')),
			note: note('period'),
			tooltip: sourceOf(orbit.periodSource, references)
		},
		axis: {
			label: m.semi_major_axis(),
			value: joinParts({
				value: sigFigures(orbit.semiMajorAxis, digits('semi_major_axis', AXIS)),
				unit: formatUnit('astronomical_unit', true)
			}),
			note: note('semi_major_axis'),
			tooltip: hint(
				angular === null ? null : arcseconds(angular),
				sourceOf(orbit.semiMajorAxisSource, references)
			)
		},
		shape: rows([
			{
				label: m.eccentricity(),
				value: sigFigures(orbit.eccentricity, digits('eccentricity')),
				note: note('eccentricity'),
				tooltip: sourceOf(orbit.eccentricitySource, references)
			},
			angle(m.inclination(), 'inclination', orbit.inclination, orbit.inclinationSource),
			angle(
				orbit.nodeAscending ? m.exoplanet_row_node() : m.system_row_either_node(),
				'node',
				orbit.node,
				orbit.nodeSource
			),
			angle(
				m.exoplanet_row_omega(),
				'arg_periastron',
				orbit.argPeriastron,
				orbit.argPeriastronSource
			),
			{
				label: m.exoplanet_row_periastron_time(),
				value: epoch.value,
				note: note('epoch'),
				tooltip: hint(epoch.tooltip, sourceOf(orbit.epochSource, references))
			},
			orbit.centre === 'primary' ? row(m.system_orbit_centre(), m.system_member_primary()) : null
		])
	};
}

function orbitRows(orbit: PairOrbit): StarRowEntry[] {
	const { period, axis, shape } = orbitElements(orbit);
	return [period, axis, ...shape];
}

/** The pair of a held star, its orbit partner, and the size of their orbit. A
 *  node of three or more members is no pair. */
function pairRows(node: SystemNode, system: StarSystem | null): StarRowEntry[] {
	const pair = node.parent === null ? undefined : system?.nodes.get(node.parent);
	if (!system || !pair) return [];
	const name = system.names.get(pair.id) || String(pair.id);
	const link = [objectRef(pair.id, name)];
	if (pair.members.length !== 2) {
		return [{ label: m.property_name_part_of(), value: '', entities: link }];
	}
	const other = systemRows(system, pair.id).find(
		({ depth, member }) => depth === 0 && member.id !== node.id
	);
	const out: StarRowEntry[] = [{ label: m.system_row_pair(), value: '', entities: link }];
	if (other) {
		const { id } = other.member;
		out.push({
			label: m.system_row_partner(),
			value: '',
			entities: [id === null ? { name: other.name } : objectRef(id, other.name)]
		});
	}
	if (pair.orbit) {
		const { period, axis } = orbitElements(pair.orbit);
		out.push(period, axis);
	}
	return out;
}

/** The place of a row with no Point source row. */
function placeRows({ ra, dec, distance }: SystemNode): StarRowEntry[] {
	return rows([
		ra !== null && dec !== null ? row(m.star_row_ra(), formatRightAscension(ra, dec, null)) : null,
		dec !== null ? row(m.star_row_dec(), formatDeclination(dec, null)) : null,
		dec !== null ? row(m.orbit_epoch(), epochLabel(SYSTEM_EPOCH)) : null,
		distance !== null
			? row(
					m.star_row_distance(),
					joinParts({ value: sigFigures(distance * PC_LY), unit: units().ly })
				)
			: null
	]);
}

function positionSection(node: SystemNode): StarSection {
	return { key: 'position', title: m.star_section_position(), rows: placeRows(node) };
}

function classification(label: string, value: string | null, note?: string): StarSection {
	const entry = row(label, value);
	return {
		key: 'classification',
		title: m.classification(),
		rows: entry ? [{ ...entry, tooltip: note }] : []
	};
}

function heldStarSections(
	node: SystemNode,
	star: HeldStarValues,
	system: StarSystem | null
): StarSection[] {
	const { references } = star;
	const kg = star.mass === null ? null : star.mass * SOLAR_MASS_KG;
	const physical = rows([
		kg === null
			? null
			: {
					label: m.star_stat_mass(),
					value: formatMass(kg),
					tooltip: hint(massComparison(kg), sourceOf(star.massSource, references))
				},
		star.radius === null
			? null
			: {
					label: m.diameter(),
					value: diameterValue(star.radius),
					tooltip: hint(
						sizeComparison(star.radius * SOLAR_RADIUS_KM),
						sourceOf(star.radiusSource, references)
					)
				},
		star.teff === null
			? null
			: {
					label: m.star_row_teff(),
					value: formatTemperature({ value: star.teff, unit: 'kelvin' }),
					tooltip: sourceOf(star.teffSource, references)
				}
	]);
	return [
		{ key: 'orbit', title: m.orbit(), rows: pairRows(node, system) },
		classification(
			m.star_stat_spectral_type(),
			spectralType(star.spectralType),
			sourceOf(star.spectralTypeSource, references)
		),
		positionSection(node),
		{ key: 'physical', title: m.physical_properties(), rows: physical }
	];
}

/** The sections of a node or a held star, in panel order. */
export function systemSections(
	record: ExtrasolarRecord,
	node: SystemNode,
	system: StarSystem | null
): StarSection[] {
	if (node.star) {
		return heldStarSections(node, node.star, system).filter(({ rows }) => rows.length > 0);
	}
	const point = starSections(record, node);
	return [
		{ key: 'orbit', title: m.orbital_elements(), rows: node.orbit ? orbitRows(node.orbit) : [] },
		...(point.length > 0 ? point : [positionSection(node)])
	].filter(({ rows }) => rows.length > 0);
}

/** A list row's figures: what the star is, then where it is. */
export function memberFigures(row: SystemRow): { what: string; where: string } {
	const { member, stars, held } = row;
	const { separation, period } = member;
	const mass = member.mass ?? held?.mass ?? null;
	const code = spectralType(member.spectralType ?? held?.spectralType ?? null);
	const solar =
		mass === null ? null : ltrIsolate(`${sigFigures(mass)}\u00a0${m.symbol_solar_mass()}`);
	const what = stars === null ? [code, solar] : [m.system_star_count({ count: stars })];
	const where = [
		separation === null ? null : arcseconds(separation),
		period === null ? null : formatPeriod(period)
	];
	return { what: what.filter(Boolean).join(' · '), where: where.filter(Boolean).join(' · ') };
}
