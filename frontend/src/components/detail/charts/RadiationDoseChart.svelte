<script lang="ts">
	/**
	 * How much dose each place delivers, as two charts rather than one.
	 *
	 * Trapped electrons and galactic cosmic rays are not one quantity: the first
	 * arrives from the planet the body orbits and kills in minutes, the second
	 * from outside the solar system and shows up as a cancer risk decades later.
	 * Sharing an axis would also make the smaller of the two unreadable — Europa
	 * is fifteen decades over Venus, so every cosmic-ray surface would draw as
	 * nothing beside it. The belts lead because they hold the largest numbers.
	 *
	 * Each figure hangs its own reading off it, following the environment's
	 * `kind` and not the size of the number, the same rule the body's panel
	 * follows: a lethal dose in minutes for the belts, added lifetime cancer
	 * risk for the surfaces.
	 */
	import type { NotableMemberEntry } from '$lib/fetch/objects/object-data';
	import { cancerRiskPerYear, formatDoseRate, timeToLethalDose } from '$lib/format/radiation';
	import * as m from '$lib/paraglide/messages.js';
	import ValuePerBodyChart from './ValuePerBodyChart.svelte';

	interface Props {
		members: NotableMemberEntry[];
		localizedNames?: Record<string, string>;
	}
	let { members, localizedNames }: Props = $props();

	/** Published beats computed, and only one of the two is ever present — the
	 *  same rule the body's own panel follows. */
	function dose(entry: NotableMemberEntry): number | undefined {
		const radiation = entry.radiation;
		return (
			radiation?.surface_dose?.sv_per_day.value ?? radiation?.modelled_surface_dose?.sv_per_day
		);
	}

	// Members with no figure are left out rather than named under the chart:
	// ten of the fourteen have none, and the page's own list already says what
	// is known about each of them instead.
	let plotted = $derived(members.filter((entry) => dose(entry) != null));
	let trapped = $derived(plotted.filter((entry) => entry.radiation?.kind === 'trapped'));
	let surfaces = $derived(plotted.filter((entry) => entry.radiation?.kind !== 'trapped'));

	function reading(svPerDay: number, entry: NotableMemberEntry): string {
		return entry.radiation?.kind === 'trapped'
			? m.radiation_lethal_in({ duration: timeToLethalDose(svPerDay) })
			: m.radiation_cancer_risk({ percent: cancerRiskPerYear(svPerDay) });
	}
</script>

<ValuePerBodyChart
	members={trapped}
	{localizedNames}
	title={m.group_radiation_belt_title()}
	value={dose}
	text={formatDoseRate}
	tooltip={reading}
/>
<ValuePerBodyChart
	members={surfaces}
	{localizedNames}
	title={m.group_radiation_surface_title()}
	value={dose}
	text={formatDoseRate}
	tooltip={reading}
/>
