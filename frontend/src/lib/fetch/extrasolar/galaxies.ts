/**
 * A galaxy of the extrasolar catalogue (`docs/export-format/extrasolar.md`,
 * "Redshift (table 4)"). Its home row holds what a galaxy catalogue gives. Its
 * object entry adds `facts`, the values that no catalogue gives
 * (`docs/export-format/objects.md`).
 */

import { fetchExtrasolarMetadata } from './files';
import { REDSHIFT_SLUG, type ExtrasolarRecord, type TableRow } from './lookup';

/** Significant figures a float32 column holds: 5.04e10 reads back 50400002048. */
const FLOAT32_DIGITS = 7;

/** A value with the bounds that its source gives. */
export interface BoundedValue {
	value: number;
	lower: number | null;
	upper: number | null;
}

/** The Redshift row of a galaxy, by column group. A group with no source is null. */
export interface GalaxyRow {
	/** ICRS place of the galaxy's point at J2016.0, degrees. */
	ra: number | null;
	dec: number | null;
	/** From the Sun to the point, pc. */
	distance: BoundedValue | null;
	distanceMethod: string | null;
	/** The revised Hubble type, as published. */
	morphologicalType: string | null;
	/** Solar masses. */
	stellarMass: BoundedValue | null;
	/** M200, solar masses. */
	totalMass: BoundedValue | null;
	/** Solar masses per year. */
	starFormationRate: BoundedValue | null;
}

/** The column groups of the Redshift row, as the object entry's `references` names them. */
export type GalaxyGroup =
	| 'position'
	| 'distance'
	| 'morphology'
	| 'stellar_mass'
	| 'total_mass'
	| 'star_formation_rate';

export function isGalaxy(record: ExtrasolarRecord): boolean {
	return record.home === REDSHIFT_SLUG;
}

function figure(row: TableRow, name: string): number | null {
	const value = row.number(name);
	if (value === null || row.container.type(name) !== 'float32') return value;
	return Number(value.toPrecision(FLOAT32_DIGITS));
}

function bounded(row: TableRow, name: string): BoundedValue | null {
	const value = figure(row, name);
	if (value === null) return null;
	return { value, lower: figure(row, `${name}_lower`), upper: figure(row, `${name}_upper`) };
}

/** The Redshift row of a record; null for a record that is no galaxy, and
 *  where the host may not show the table. */
export function galaxyRow(record: ExtrasolarRecord): GalaxyRow | null {
	const row = record.rows.get(REDSHIFT_SLUG);
	if (!row) return null;
	return {
		ra: row.number('ra'),
		dec: row.number('dec'),
		distance: bounded(row, 'distance'),
		distanceMethod: row.text('distance_method'),
		morphologicalType: row.text('morphological_type'),
		stellarMass: bounded(row, 'stellar_mass'),
		totalMass: bounded(row, 'total_mass'),
		starFormationRate: bounded(row, 'star_formation_rate')
	};
}

/** The ID of the galaxy that holds the Sun. Null where the host serves no
 *  extrasolar export, or the export names no such galaxy. */
export async function homeGalaxyId(): Promise<number | null> {
	return (await fetchExtrasolarMetadata())?.home_galaxy ?? null;
}

/** How many objects of each kind the app holds; null for a kind with none. */
export interface CatalogueCounts {
	stars: number | null;
	starSystems: number | null;
	planets: number | null;
}

/** The counts of /about/data, from its kinds: the Sun and its planets are in
 *  them, and the census of the extrasolar export has neither. */
export function catalogueCounts(kinds: readonly { id: string; count: number }[]): CatalogueCounts {
	const count = (id: string) => kinds.find((kind) => kind.id === id)?.count ?? null;
	return { stars: count('star'), starSystems: count('star_system'), planets: count('planet') };
}
