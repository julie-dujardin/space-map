<script lang="ts" module>
	import { earthRatioParts, formatUnit, scientificNotation } from '$lib/format/quantities';
	import * as m from '$lib/paraglide/messages.js';

	/**
	 * Water volume, in the unit it was measured in. The exponent is a literal —
	 * Wikidata has no cubic-kilometre `unit_*` row, same reason the tilt card
	 * writes its own degree sign. Scientific notation, not a compact suffix:
	 * these span two decades and "27B km³" is ambiguous and unfamiliar.
	 */
	export function oceanVolume(km3: number): string {
		return `${scientificNotation(km3)} ${formatUnit('kilometre', true)}³`;
	}

	/**
	 * Volume against Earth's ocean, for the tooltip. Null at parity — Earth's own
	 * row gets none, since it's the ruler here, not the subject, and "1×
	 * Earth's ocean" tells nobody anything.
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
