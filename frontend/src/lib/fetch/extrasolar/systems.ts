/**
 * Star systems, read from their System rows
 * (`docs/export-format/extrasolar.md`, "System (table 3)"). The row of a root
 * holds the tree of the system's nodes. The row of each node holds its members.
 */

import type { CrossId } from './container';
import type { ValueReference } from '$lib/fetch/objects/object-data';
import { measuredRadiusSolar } from '$lib/scene/starfield/record';
import {
	POINT_SOURCE_SLUG,
	SYSTEM_SLUG,
	TableRow,
	extrasolarLookup,
	systemPrimary,
	type ExtrasolarLookup,
	type ExtrasolarRecord
} from './lookup';

export type MemberKind = 'star' | 'system' | 'held star' | 'entry';

/** The work behind values of the export. A page shows `short` and `title`,
 *  else `reference`, and links them to `url`. */
export interface SystemCitation {
	source: string | null;
	reference: string | null;
	short: string | null;
	title: string | null;
	url: string | null;
}

/** A direct member of a node. */
export interface SystemMember {
	/** Null for an entry. */
	id: number | null;
	kind: MemberKind;
	letter: string | null;
	/** An entry's letters within its point (`Ca` of `Cab`). */
	inner: string | null;
	label: string | null;
	source: string | null;
	spectralType: string | null;
	vMag: number | null;
	gMag: number | null;
	/** Solar masses. */
	mass: number | null;
	/** From the node's primary (arcsec). */
	separation: number | null;
	/** Degrees. */
	positionAngle: number | null;
	/** Days. */
	period: number | null;
	eccentricity: number | null;
	/** Arcsec. */
	semiMajorAxis: number | null;
	/** How the member is known: `visual`, `spectroscopic orbit` and so on. */
	known: string[];
	/** The catalogue ids of an entry. */
	ids: CrossId[];
}

/** A node of a system's tree. */
export interface SystemTreeNode {
	id: number;
	/** Null at the root. */
	parent: number | null;
	point: boolean;
	stars: number;
	label: string | null;
	/** Its Metadata class: `star` for a held star. */
	class: string | null;
}

/**
 * The orbit of a pair's second member about its first. `a` to `phase` are the
 * scene's elements: ecliptic and mean equinox of J2000. The elements from
 * `inclination` to `arg_periastron` are on the plane of the sky.
 */
export interface PairOrbit {
	/** Semi-major axis of the relative orbit (AU). */
	a: number;
	e: number;
	/** Degrees. */
	i: number;
	om: number;
	w: number;
	ma: number;
	/** Mean motion (deg/day). */
	n: number;
	/** JD of `ma`, in the time scale of its source. */
	epoch: number;
	/** What fixes `ma`: `periastron`, `eclipse`, `osculating` or `assumed`. */
	phase: string;
	/** Days. */
	period: number;
	/** AU. */
	semiMajorAxis: number;
	/** Null when a source gives AU or Kepler's third law gives it. */
	semiMajorAxisArcsec: number | null;
	eccentricity: number;
	/** To the plane of the sky (deg). Under 90 the second member turns north to east. */
	inclination: number;
	/** Position angle of the node, north through east (deg). */
	node: number;
	/** True when `node` is the ascending node; false when it can be either node. */
	nodeAscending: boolean;
	/** Of the second member, from `node` (deg). */
	argPeriastron: number;
	/** JD. */
	periastronTime: number;
	/** The barycentre on the line from the first member to the second, as a
	 *  share of their separation. 0 with no mass ratio. */
	barycentre: number;
	/** `barycentre`; `primary` when the first member stays at the centre. */
	centre: string;
	massRatioSource: string | null;
	periodSource: string | null;
	semiMajorAxisSource: string | null;
	eccentricitySource: string | null;
	inclinationSource: string | null;
	nodeSource: string | null;
	argPeriastronSource: string | null;
	epochSource: string | null;
	/** The elements that a rule fills. */
	assumed: string[];
	/** The elements that other values give. */
	computed: string[];
	references: SystemCitation[];
}

/** The values of a held star. */
export interface HeldStarValues {
	/** Solar masses. */
	mass: number | null;
	/** Nominal solar radii. */
	radius: number | null;
	/** K. */
	teff: number | null;
	spectralType: string | null;
	massSource: string | null;
	radiusSource: string | null;
	teffSource: string | null;
	spectralTypeSource: string | null;
	references: SystemCitation[];
}

/** A System row: a point, a resolved system or a held star. */
export interface SystemNode {
	id: number;
	point: boolean;
	depth: number;
	stars: number;
	/** ICRS at J2016.0 of the node's primary point (deg). */
	ra: number | null;
	dec: number | null;
	label: string | null;
	spectralType: string | null;
	evidence: string | null;
	sources: string[];
	treeSource: string | null;
	/** Null at the root. */
	parent: number | null;
	root: number;
	/** Null for a held star. */
	primary: number | null;
	/** Pc; null when no star of the node has a distance. */
	distance: number | null;
	members: SystemMember[];
	/** Every node of the system, on the root's row; null on any other row. */
	tree: SystemTreeNode[] | null;
	/** On a pair whose orbit can be drawn. */
	orbit: PairOrbit | null;
	/** On a held star. */
	star: HeldStarValues | null;
	/** What a paper or an angular diameter gives for a point, in nominal solar
	 *  radii. */
	measuredRadius: number | null;
	measuredBy: 'paper' | 'angular diameter' | null;
	/** The papers behind `measuredRadius`, once a system's load fills them. */
	radiusPapers: ValueReference[];
}

/** The items of a list column on `row`; each item reads as a row of the item
 *  columns. Null for a null row. */
function items(row: TableRow, list: string): TableRow[] | null {
	const span = row.container.list(list).items(row.row);
	if (!span) return null;
	const out: TableRow[] = [];
	for (let i = span[0]; i < span[1]; i++) {
		out.push(new TableRow(row.slug, row.table, row.container, i));
	}
	return out;
}

function words(row: TableRow, list: string): string[] {
	return (items(row, list) ?? []).flatMap((item) => item.text(`${list}.item`) ?? []);
}

function citations(row: TableRow, list: string): SystemCitation[] {
	return (items(row, list) ?? []).map((item) => ({
		source: item.text(`${list}.source`),
		reference: item.text(`${list}.reference`),
		short: item.text(`${list}.short`),
		title: item.text(`${list}.title`),
		url: item.text(`${list}.url`)
	}));
}

function member(item: TableRow): SystemMember {
	return {
		id: item.number('members.id'),
		kind: item.text('members.kind') as MemberKind,
		letter: item.text('members.letter'),
		inner: item.text('members.inner'),
		label: item.text('members.label'),
		source: item.text('members.source'),
		spectralType: item.text('members.spectral_type'),
		vMag: item.number('members.v_mag'),
		gMag: item.number('members.g_mag'),
		mass: item.number('members.mass'),
		separation: item.number('members.separation'),
		positionAngle: item.number('members.position_angle'),
		period: item.number('members.period'),
		eccentricity: item.number('members.eccentricity'),
		semiMajorAxis: item.number('members.semi_major_axis'),
		known: words(item, 'members.known'),
		ids: item.crossIds('members.ids')
	};
}

function treeNode(item: TableRow): SystemTreeNode {
	return {
		id: item.number('tree.id')!,
		parent: item.number('tree.parent'),
		point: item.flag('tree.point')!,
		stars: item.number('tree.stars')!,
		label: item.text('tree.label'),
		class: item.text('tree.class')
	};
}

function pairOrbit(item: TableRow): PairOrbit {
	return {
		a: item.number('orbit.a')!,
		e: item.number('orbit.e')!,
		i: item.number('orbit.i')!,
		om: item.number('orbit.om')!,
		w: item.number('orbit.w')!,
		ma: item.number('orbit.ma')!,
		n: item.number('orbit.n')!,
		epoch: item.number('orbit.epoch')!,
		phase: item.text('orbit.phase')!,
		period: item.number('orbit.period')!,
		semiMajorAxis: item.number('orbit.semi_major_axis')!,
		semiMajorAxisArcsec: item.number('orbit.semi_major_axis_arcsec'),
		eccentricity: item.number('orbit.eccentricity')!,
		inclination: item.number('orbit.inclination')!,
		node: item.number('orbit.node')!,
		nodeAscending: item.flag('orbit.node_ascending')!,
		argPeriastron: item.number('orbit.arg_periastron')!,
		periastronTime: item.number('orbit.periastron_time')!,
		barycentre: item.number('orbit.barycentre')!,
		centre: item.text('orbit.centre')!,
		massRatioSource: item.text('orbit.mass_ratio_source'),
		periodSource: item.text('orbit.period_source'),
		semiMajorAxisSource: item.text('orbit.semi_major_axis_source'),
		eccentricitySource: item.text('orbit.eccentricity_source'),
		inclinationSource: item.text('orbit.inclination_source'),
		nodeSource: item.text('orbit.node_source'),
		argPeriastronSource: item.text('orbit.arg_periastron_source'),
		epochSource: item.text('orbit.epoch_source'),
		assumed: words(item, 'orbit.assumed'),
		computed: words(item, 'orbit.computed'),
		references: citations(item, 'orbit.references')
	};
}

function heldStarValues(item: TableRow): HeldStarValues {
	return {
		mass: item.number('star.mass'),
		radius: item.number('star.radius'),
		teff: item.number('star.teff'),
		spectralType: item.text('star.spectral_type'),
		massSource: item.text('star.mass_source'),
		radiusSource: item.text('star.radius_source'),
		teffSource: item.text('star.teff_source'),
		spectralTypeSource: item.text('star.spectral_type_source'),
		references: citations(item, 'star.references')
	};
}

/** The System row of a record, or null for an ID with none. */
export function systemNode(record: ExtrasolarRecord): SystemNode | null {
	const row = record.rows.get(SYSTEM_SLUG);
	if (!row) return null;
	const orbit = items(row, 'orbit')?.[0];
	const star = items(row, 'star')?.[0];
	const ps = record.rows.get(POINT_SOURCE_SLUG);
	const measuredRadius = ps ? measuredRadiusSolar(ps) : null;
	const paper = ps?.number('radius_literature') != null;
	return {
		id: record.id,
		point: row.flag('point')!,
		depth: row.number('depth')!,
		stars: row.number('stars')!,
		ra: row.number('ra'),
		dec: row.number('dec'),
		label: row.text('label'),
		spectralType: row.text('spectral_type'),
		evidence: row.text('evidence'),
		sources: words(row, 'sources'),
		treeSource: row.text('tree_source'),
		parent: row.number('parent'),
		root: row.number('root')!,
		primary: row.number('primary'),
		distance: row.number('distance'),
		members: (items(row, 'members') ?? []).map(member),
		tree: items(row, 'tree')?.map(treeNode) ?? null,
		orbit: orbit ? pairOrbit(orbit) : null,
		star: star ? heldStarValues(star) : null,
		measuredRadius,
		measuredBy: measuredRadius === null ? null : paper ? 'paper' : 'angular diameter',
		radiusPapers: []
	};
}

/** The root of the system of a record; null for an ID in no system. A root
 *  has no Metadata `system`, but it has a System row. */
export function systemRoot(record: ExtrasolarRecord): number | null {
	return record.metadata.system ?? (record.rows.has(SYSTEM_SLUG) ? record.id : null);
}

/** Whether a record is several stars. Such an object has no size, type or star
 *  family of its own: those belong to its members. */
export function isStarSystem({ metadata }: ExtrasolarRecord): boolean {
	return metadata.class === 'binary star' || metadata.class === 'multiple star';
}

/** The ID one step toward the light of a record: its own, the primary of a
 *  node, or for a held star its node, which can be a resolved node. */
export function pointOf(record: ExtrasolarRecord): number {
	const parent = record.rows.get(SYSTEM_SLUG)?.number('parent');
	return systemPrimary(record) ?? parent ?? record.id;
}

/** The IDs with a point of their own: the points of the tree and the member
 *  stars of `nodes`, the rows of the system's nodes. A held star and an entry
 *  have no point. */
export function systemPointIds(
	tree: readonly SystemTreeNode[],
	nodes: readonly SystemNode[]
): number[] {
	const ids = new Set<number>();
	for (const node of tree) if (node.point) ids.add(node.id);
	for (const { members } of nodes) {
		for (const { kind, id } of members) if (kind === 'star' && id !== null) ids.add(id);
	}
	return [...ids];
}

/** The rows of the tree of `root`, root first. Empty when the host may not
 *  show its rows. */
export async function loadSystemNodes(
	root: number,
	lookup: Pick<ExtrasolarLookup, 'live'> = extrasolarLookup
): Promise<SystemNode[]> {
	const nodeOf = async (id: number): Promise<SystemNode | null> => {
		const result = await lookup.live(id);
		return result.kind === 'live' ? systemNode(result.record) : null;
	};
	const top = await nodeOf(root);
	if (!top?.tree) return [];
	const rest = await Promise.all(top.tree.filter((n) => n.id !== root).map((n) => nodeOf(n.id)));
	return [top, ...rest.filter((node) => node !== null)];
}
