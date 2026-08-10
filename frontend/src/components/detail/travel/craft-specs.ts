/**
 * The craft's published figures, as rows.
 *
 * A function rather than a component because the two halves are drawn apart:
 * the table sits with the trajectory it explains, and the works behind it go to
 * the foot of the panel with everything else that is cited.
 */

import { crewCapacity, maxPayloadKgForRoute, type Route, type Vehicle } from '$lib/math/travel';
import { formatDurationNarrow } from '$lib/format/duration';
import {
	formatCompactCurrency,
	formatNumber,
	formatQuantity,
	ucfirst
} from '$lib/format/quantities';
import { formatAcceleration, formatDv } from '$lib/travel/format';
import { sourceCitation, type SourceCitation } from '$lib/travel/vehicles';
import * as m from '$lib/paraglide/messages.js';
import { vehiclePowerLabel, vehiclePropulsionLabel, vehicleStatusLabel } from './vehicle-labels';

export interface CraftSpec {
	label: string;
	value: string;
	/** A qualifier the figure cannot carry, like the year a price is in. */
	note?: string;
	/** Source key behind the figure, resolved by `craftSpecSources`. */
	source?: string;
}

function kilograms(kg: number): string {
	return formatQuantity({ value: Math.round(kg), unit: 'kilogram' }, true);
}

/**
 * What the catalogue publishes about this craft, in the order it matters to a
 * trajectory: what it can spend, what it is made of, what it can hold, and what
 * it cost. Anything the route works out from these figures belongs to the
 * sections that do the working out, not here.
 */
export function craftSpecs(vehicle: Vehicle, route: Route): CraftSpec[] {
	const specs: CraftSpec[] = [];

	// What kind of craft this is, before what it can do. Written as the picker
	// writes them, capitalised because a row's value opens its own line.
	const propulsion = vehiclePropulsionLabel(vehicle);
	if (propulsion) specs.push({ label: m.travel_spec_propulsion(), value: ucfirst(propulsion) });
	const status = vehicleStatusLabel(vehicle);
	if (status) specs.push({ label: m.travel_spec_status(), value: ucfirst(status) });

	// Δv is derived from the masses and the engine rather than published, so it
	// carries no source of its own — the three rows under it are its citation.
	if (vehicle.unlimitedDv) {
		specs.push({ label: m.travel_spec_dv(), value: m.travel_dv_unlimited() });
	} else if (vehicle.dvKms !== undefined) {
		specs.push({ label: m.travel_spec_dv(), value: formatDv(vehicle.dvKms) });
	}
	if (vehicle.accelMs2) {
		specs.push({
			label: m.travel_drive_accel(),
			value: formatAcceleration(vehicle.accelMs2.value),
			source: vehicle.accelMs2.source
		});
	}
	// A launcher has no budget of its own and no masses to state one from: what
	// it can do is lift, and how much depends on where the trip is going.
	if (vehicle.kind === 'launcher') {
		const liftKg = maxPayloadKgForRoute(vehicle, route);
		if (liftKg !== null) {
			specs.push({
				label: m.travel_spec_lift(),
				value: kilograms(liftKg),
				source: vehicle.c3Curve?.source
			});
		}
	}
	if (vehicle.dryMassKg) {
		specs.push({
			label: m.travel_spec_dry_mass(),
			value: kilograms(vehicle.dryMassKg.value),
			source: vehicle.dryMassKg.source
		});
	}
	if (vehicle.propellantMassKg) {
		specs.push({
			label: m.travel_spec_propellant(),
			value: kilograms(vehicle.propellantMassKg.value),
			source: vehicle.propellantMassKg.source
		});
	}
	if (vehicle.ispS) {
		specs.push({
			label: m.travel_spec_isp(),
			value: m.travel_unit_s({ value: formatNumber(vehicle.ispS.value) }),
			source: vehicle.ispS.source
		});
	}
	if (vehicle.thrustN) {
		specs.push({
			label: m.travel_spec_thrust(),
			value: m.travel_unit_n({ value: formatNumber(vehicle.thrustN.value) }),
			source: vehicle.thrustN.source
		});
	}
	const power = vehiclePowerLabel(vehicle);
	if (power) specs.push({ label: m.travel_spec_power(), value: power });

	const seats = crewCapacity(vehicle);
	if (seats) {
		specs.push({ label: m.travel_seats(), value: String(seats), source: vehicle.crew?.source });
	}
	if (vehicle.enduranceDays) {
		specs.push({
			label: m.travel_spec_endurance(),
			value: formatDurationNarrow(vehicle.enduranceDays.value),
			source: vehicle.enduranceDays.source
		});
	}
	if (vehicle.payloadCapacityKg) {
		specs.push({
			label: m.travel_spec_hold(),
			value: kilograms(vehicle.payloadCapacityKg.value),
			source: vehicle.payloadCapacityKg.source
		});
	}
	// The fastest it can meet an atmosphere, which the arrival is measured
	// against — and the only figure here that can rule a trajectory out outright.
	if (vehicle.maxEntrySpeedKms) {
		specs.push({
			label: m.travel_spec_entry_limit(),
			value: formatDv(vehicle.maxEntrySpeedKms.value),
			source: vehicle.maxEntrySpeedKms.source
		});
	}
	if (vehicle.cost) {
		// A launch is bought by the flight and a spacecraft is built by the unit,
		// so the two prices are not the same kind of figure and do not share a row.
		const label =
			vehicle.cost.kind === 'unit'
				? m.travel_spec_cost_unit()
				: vehicle.cost.kind === 'launch_service'
					? m.travel_spec_cost_launch()
					: m.travel_spec_cost();
		specs.push({
			label,
			value: formatCompactCurrency({ value: vehicle.cost.usdMillions * 1e6, currency: 'USD' }),
			note: String(vehicle.cost.year),
			source: vehicle.cost.source
		});
	}
	return specs;
}

/** The works behind the rows, once each and in the order they are first cited. */
export function craftSpecSources(specs: readonly CraftSpec[]): SourceCitation[] {
	const seen = new Set<string>();
	const sources: SourceCitation[] = [];
	for (const spec of specs) {
		if (!spec.source || seen.has(spec.source)) continue;
		seen.add(spec.source);
		const citation = sourceCitation(spec.source);
		if (citation) sources.push(citation);
	}
	return sources;
}
