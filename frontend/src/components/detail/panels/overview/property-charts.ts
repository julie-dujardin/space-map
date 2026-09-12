/** The chart each Structure & Activity collection draws its members as, keyed
 *  by property so a new collection cannot reach the overview without one. */

import type { Component, ComponentProps } from 'svelte';
import type { NotableMemberEntry } from '$lib/fetch/objects/object-data';
import type { PropertyKind } from '$lib/state/category-config';
import { fieldParts, powerParts } from '$lib/format/activity';
import AtmospherePressureChart from '../../charts/AtmospherePressureChart.svelte';
import OceanVolumeChart from '../../charts/OceanVolumeChart.svelte';
import RadiationDoseChart from '../../charts/RadiationDoseChart.svelte';
import TectonicStyleChart from '../../charts/TectonicStyleChart.svelte';
import ValuePerBodyChart from '../../charts/ValuePerBodyChart.svelte';
import VolcanismStatusChart from '../../charts/VolcanismStatusChart.svelte';
import * as m from '$lib/paraglide/messages.js';

/** The members every one of these charts plots, and the names to label them
 *  with — the two charts that only tally their members ignore the names. */
export interface MemberChartProps {
	members: NotableMemberEntry[];
	localizedNames?: Record<string, string>;
}

export interface PropertyChart {
	component: Component<MemberChartProps>;
	/** What this page plots beyond the members. Built at render, so the titles
	 *  follow the active locale rather than the one loaded first. */
	extra?: () => Record<string, unknown>;
}

type ValueChartProps = ComponentProps<typeof ValuePerBodyChart>;

/** One figure per body, titled by the page that plots it. The cast hands the
 *  table a chart of the shared shape; `extra` carries what this one needs on
 *  top, and its type makes each page supply all of it. */
function valueChart(extra: () => Omit<ValueChartProps, keyof MemberChartProps>): PropertyChart {
	return { component: ValuePerBodyChart as Component<MemberChartProps>, extra };
}

export const PROPERTY_CHART: Record<PropertyKind, PropertyChart> = {
	atmospheres: { component: AtmospherePressureChart },
	oceans: { component: OceanVolumeChart },
	volcanism: { component: VolcanismStatusChart },
	tectonics: { component: TectonicStyleChart },
	'magnetic-fields': valueChart(() => ({
		title: m.group_magnetic_field_title(),
		// A published bound is not a measurement, so it plots nothing.
		value: (entry) =>
			entry.activity?.magnetism?.surface_field_t_upper_limit
				? undefined
				: entry.activity?.magnetism?.surface_field_t,
		text: (v) => `${fieldParts(v).value} ${fieldParts(v).unit}`
	})),
	'tidal-heating': valueChart(() => ({
		title: m.group_tidal_power_title(),
		value: (entry) => entry.activity?.tidal?.power_w,
		text: (v) => `${powerParts(v).value} ${powerParts(v).unit}`
	})),
	radiation: { component: RadiationDoseChart }
};
