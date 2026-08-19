/** The reading under each member's name on a Structure & Activity collection
 *  page: whatever that page ranks by. */

import type { NotableMemberEntry, MemberActivity } from '$lib/fetch/objects/object-data';
import type { PropertyKind } from '$lib/state/category-config';
import { formatPressure } from '$lib/format/pressure';
import { formatDoseRate } from '$lib/format/radiation';
import {
	fieldKindLabel,
	fieldParts,
	powerParts,
	statusLabel,
	tectonicStyleLabel,
	tidalRoleLabel,
	volcanismLabel
} from '$lib/format/activity';
import { ucfirst } from '$lib/format/quantities';
import { oceanVolume } from '../../charts/OceanVolumeChart.svelte';
import * as m from '$lib/paraglide/messages.js';

export function propertyFigure(
	member: NotableMemberEntry,
	property: PropertyKind | null
): string | undefined {
	if (member.ocean) return oceanVolume(member.ocean.volume_km3);
	if (member.atmosphere_pressure) return formatPressure(member.atmosphere_pressure.pa);
	if (property === 'radiation') return radiation(member.radiation);
	const activity = member.activity;
	if (!activity) return undefined;
	switch (property) {
		case 'volcanism':
			return activity.volcanism ? ucfirst(volcanismLabel(activity.volcanism)) : undefined;
		case 'tectonics':
			return tectonics(activity.tectonics);
		case 'magnetic-fields':
			return magnetism(activity.magnetism);
		case 'tidal-heating':
			return tide(activity.tidal);
		default:
			return undefined;
	}
}

/** The field a reader could stand on the body and measure, or — where nobody
 *  has — what kind of field it is at all. */
function magnetism(field: MemberActivity['magnetism']): string | undefined {
	if (!field) return undefined;
	if (field.surface_field_t == null) return ucfirst(fieldKindLabel(field.kind));
	const reading = fieldParts(field.surface_field_t);
	const text = `${reading.value} ${reading.unit}`;
	return field.surface_field_t_upper_limit ? `< ${text}` : text;
}

/** How the crust behaves, qualified where nobody has watched it do so —
 *  the same rule volcanism's rows follow, since six of the ten are
 *  "probable" and dropping that would make them read as observed. */
function tectonics(style: MemberActivity['tectonics']): string | undefined {
	if (!style) return undefined;
	const label = ucfirst(tectonicStyleLabel(style.style));
	if (style.status === 'active') return label;
	return m.activity_qualified({ value: label, status: statusLabel(style.status) });
}

/** The wattage where it is published, and what the tide is for that body
 *  where it is not — which is what its sources do commit to. */
function tide(tidal: MemberActivity['tidal']): string | undefined {
	if (!tidal) return undefined;
	if (tidal.power_w == null) return ucfirst(tidalRoleLabel(tidal.role));
	const reading = powerParts(tidal.power_w);
	return `${reading.value} ${reading.unit}`;
}

/** What a dosimeter would read. Every member has one — a figure is what puts
 *  a body on that page, so the row never falls back to prose. */
function radiation(entry: NotableMemberEntry['radiation']): string | undefined {
	if (!entry) return undefined;
	const dose = entry.surface_dose?.sv_per_day.value ?? entry.modelled_surface_dose?.sv_per_day;
	return dose != null ? formatDoseRate(dose) : undefined;
}
