/**
 * Craft you can filter the trajectories by.
 *
 * IMPORTANT: these figures are approximate, rounded, and not sourced. They are
 * the right order of magnitude and put the vehicles in the right relative
 * order, which is enough to answer "could this thing make that trip" — but they
 * are not published performance data and the UI says so. Replace them with
 * cited values (NASA's Launch Services Program publishes C3/payload curves)
 * before treating any number here as a fact.
 *
 * A launcher is judged on the launch energy it can reach; a spacecraft on the
 * Δv it carries once it is up there. Nothing here models low thrust, so the
 * electric craft are deliberately absent rather than wrongly rated.
 */

import type { Vehicle } from '$lib/math/travel';

export interface CatalogueEntry extends Vehicle {
	/** Message key suffix for the display name, under `vehicle_*`. */
	nameKey: string;
}

export const VEHICLE_CATALOGUE: readonly CatalogueEntry[] = [
	{
		id: 'falcon-heavy',
		nameKey: 'falcon_heavy',
		kind: 'launcher',
		propulsion: 'chemical',
		dvKms: 0,
		c3Curve: [
			[0, 15000],
			[20, 9500],
			[40, 6000],
			[60, 3800],
			[100, 1500]
		]
	},
	{
		id: 'sls-block-1b',
		nameKey: 'sls_block_1b',
		kind: 'launcher',
		propulsion: 'chemical',
		dvKms: 0,
		c3Curve: [
			[0, 27000],
			[20, 18000],
			[40, 12000],
			[60, 8000],
			[100, 4000]
		]
	},
	{ id: 'apollo-csm', nameKey: 'apollo_csm', kind: 'crewed', propulsion: 'chemical', dvKms: 2.8 },
	{
		id: 'starship',
		nameKey: 'starship',
		kind: 'crewed',
		propulsion: 'chemical',
		dvKms: 6.9
	},
	{ id: 'epstein', nameKey: 'epstein', kind: 'fictional', propulsion: 'fictional', dvKms: 3000 }
];

export function findVehicle(id: string | null): CatalogueEntry | null {
	if (!id) return null;
	return VEHICLE_CATALOGUE.find((v) => v.id === id) ?? null;
}
