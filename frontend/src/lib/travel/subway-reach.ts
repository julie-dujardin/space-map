/**
 * What a chosen craft can pay for on the Δv map.
 *
 * Counted from the origin's parking orbit: ascent is the launcher's bill, the
 * same split `checkFeasibility` makes, so a spacecraft is judged on the budget
 * it actually carries. Everything the budget does not reach is drawn greyed.
 */

import { canAeroAssist, type Vehicle } from '$lib/math/travel';
import type { Tree, TreeRow } from './subway-tree';

export interface Reach {
	/** Stop ids the budget covers, in the tree's own station ids. */
	stops: ReadonlySet<string>;
	/** Δv the craft brings, km/s; Infinity where propellant is no constraint. */
	budgetKms: number;
}

/**
 * The in-space Δv the map can weigh a craft by, or null where nothing
 * published says. A launcher spends its performance before the count starts
 * and states it as a payload curve rather than a budget, so it has no answer
 * here and nothing it flies with is greyed out.
 */
export function craftBudgetKms(vehicle: Vehicle): number | null {
	if (vehicle.unlimitedDv) return Infinity;
	return vehicle.dvKms ?? null;
}

/** What an atmosphere takes off a row's arrival, where the craft has
 *  something to fly a pass behind. Nothing anywhere else on the row: the
 *  kernel prices the whole approach at once, so the saving belongs to the
 *  stops past the intercept. */
function aeroSavings(row: TreeRow, aero: boolean): { orbit: number; surface: number } {
	const totals = row.totals;
	if (!aero || !totals) return { orbit: 0, surface: 0 };
	const orbit =
		totals.aeroOrbitKms === null ? 0 : Math.max(0, totals.orbitKms - totals.aeroOrbitKms);
	const surface =
		totals.surfaceKms === null || totals.aeroSurfaceKms === null
			? 0
			: Math.max(0, totals.surfaceKms - totals.aeroSurfaceKms);
	return { orbit, surface };
}

/**
 * Every stop the craft's budget reaches. Null when the craft states no budget
 * the map can read, which is a shrug rather than a refusal: the map is then
 * drawn as it is without one.
 */
export function craftReach(tree: Tree, vehicle: Vehicle): Reach | null {
	const budgetKms = craftBudgetKms(vehicle);
	if (budgetKms === null) return null;

	const aero = canAeroAssist(vehicle);
	const stops = new Set<string>();
	const spend = (station: string, kms: number): number => {
		if (kms <= budgetKms) stops.add(station);
		return kms;
	};

	// The ground and the parking orbit above it are where the count starts, so
	// both are free whatever the craft carries.
	const ground = tree.trunk[0]?.kind === 'surface';
	const orbitIndex = ground ? 1 : 0;
	const trunkKms: number[] = [];
	for (let i = 0; i < tree.trunk.length; i++) {
		const kms = i <= orbitIndex ? 0 : trunkKms[i - 1] + tree.trunkLegs[i - 1].dvKms;
		trunkKms[i] = spend(tree.trunk[i].station, kms);
	}

	const walk = (row: TreeRow, fromKms: number): void => {
		const saved = aeroSavings(row, aero);
		let kms = fromKms + row.depart.dvKms;
		const entryKms = kms;
		row.stops.forEach((stop, i) => {
			if (i > 0) kms += row.legs[i - 1].dvKms;
			const discount =
				stop.kind === 'surface'
					? saved.surface
					: stop.kind === 'escape' || stop.kind === 'orbit'
						? saved.orbit
						: 0;
			spend(stop.station, Math.max(entryKms, kms - discount));
		});
		// Moons hang off the intercept stop their planet's row shares with them.
		for (const moon of row.moons) walk(moon, entryKms);
	};
	for (const row of tree.rows) walk(row, trunkKms[row.trunkIndex]);

	return { stops, budgetKms };
}
