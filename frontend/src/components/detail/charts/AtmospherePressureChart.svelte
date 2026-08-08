<script lang="ts">
	/**
	 * How much air each body holds, at the level its source quotes.
	 *
	 * The level rides in the footnote rather than on each row, because it is
	 * what stops the four giants' identical 0.1 bar from reading as a surface.
	 */
	import type { NotableMemberEntry } from '$lib/fetch/objects/object-data';
	import { formatPressure, pressureLevelLabel } from '$lib/format/pressure';
	import * as m from '$lib/paraglide/messages.js';
	import ValuePerBodyChart from './ValuePerBodyChart.svelte';

	interface Props {
		members: NotableMemberEntry[];
		localizedNames?: Record<string, string>;
	}
	let { members, localizedNames }: Props = $props();

	/** The levels in play, so the chart says once what its figures are quoted
	 *  at instead of repeating "cloud top" on four rows. */
	let levels = $derived([
		...new Set(members.map((entry) => entry.atmosphere_pressure?.level).filter((l) => l != null))
	]);
</script>

<ValuePerBodyChart
	{members}
	{localizedNames}
	title={m.group_atmosphere_pressure_title()}
	value={(entry) => entry.atmosphere_pressure?.pa}
	text={formatPressure}
	note={m.group_atmosphere_pressure_levels({
		levels: levels.map((level) => pressureLevelLabel(level)).join(', ')
	})}
/>
