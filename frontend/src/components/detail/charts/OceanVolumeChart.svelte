<script lang="ts" module>
	import { earthRatioParts, formatUnit, scientificNotation } from '$lib/format/quantities';
	import * as m from '$lib/paraglide/messages.js';

	/**
	 * How much water there is, in the unit it was measured in.
	 *
	 * The exponent is a literal because `unit_*` labels are generated from
	 * Wikidata and there is no cubic-kilometre row — the same reason the tilt
	 * card writes its own degree sign. Scientific notation rather than a compact
	 * suffix: these span two decades and "27B km³" is both ambiguous and a
	 * number nobody holds.
	 */
	export function oceanVolume(km3: number): string {
		return `${scientificNotation(km3)} ${formatUnit('kilometre', true)}³`;
	}

	/**
	 * The same volume against the only ocean anyone has a feel for, for the
	 * tooltip the figure hangs off.
	 *
	 * Null at parity, so Earth's own row simply has none — it is the ruler here
	 * rather than the subject, and "1× Earth's ocean" is the one comparison that
	 * cannot inform anyone.
	 */
	export function earthOceans(ratio: number): string | null {
		const parts = earthRatioParts(ratio);
		if (!parts) return null;
		return 'multiple' in parts
			? m.ocean_earth_times({ value: parts.multiple })
			: m.ocean_earth_percent({ value: parts.percent });
	}
</script>

<script lang="ts">
	import type { NotableMemberEntry } from '$lib/fetch/objects/object-data';
	import ValuePerBodyChart from './ValuePerBodyChart.svelte';

	interface Props {
		members: NotableMemberEntry[];
		localizedNames?: Record<string, string>;
	}
	let { members, localizedNames }: Props = $props();

	/** Earth's own, the denominator every tooltip is quoted against. */
	const EARTH_ID = 'naif-399';

	let earthVolume = $derived(
		members.find((entry) => entry.id === EARTH_ID)?.ocean?.volume_km3 ?? null
	);
</script>

<ValuePerBodyChart
	{members}
	{localizedNames}
	title={m.group_ocean_volume_title()}
	value={(entry) => entry.ocean?.volume_km3}
	text={oceanVolume}
	tooltip={(km3) => (earthVolume ? (earthOceans(km3 / earthVolume) ?? undefined) : undefined)}
/>
