<script lang="ts" module>
	import { earthRatioParts, joinParts, scientificNotation } from '$lib/format/quantities';
	import * as m from '$lib/paraglide/messages.js';

	/**
	 * Water volume, in the unit it was measured in. Its own symbol rather than a
	 * superscript after the kilometre one, which Chinese writes 立方千米 and the
	 * glued form rendered 公里³. Scientific notation, not a compact suffix: these
	 * span two decades and "27B km³" is ambiguous and unfamiliar.
	 */
	export function oceanVolume(km3: number): string {
		return joinParts({ value: scientificNotation(km3), unit: m.symbol_cubic_kilometre() });
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
	import { evidenceName, standingName } from '$lib/charts/interior-layers';
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

	/** How the ocean was found, and whether it is agreed on, after the volume.
	 *  Four of these bars are what a model requires rather than what anyone
	 *  detected, and a bar length cannot say so. */
	function provenance(ocean: NotableMemberEntry['ocean']): string | undefined {
		const parts = [
			ocean?.standing ? standingName(ocean.standing) : null,
			ocean?.evidence ? evidenceName(ocean.evidence) : null
		].filter(Boolean);
		return parts.length ? parts.join(' · ') : undefined;
	}

	/** Only where some row on this page has one, so a page of measured oceans
	 *  is not told that some of them might not be there. */
	let anyContested = $derived(members.some((entry) => entry.ocean?.standing));
</script>

<ValuePerBodyChart
	{members}
	{localizedNames}
	title={m.group_ocean_volume_title()}
	value={(entry) => entry.ocean?.volume_km3}
	text={oceanVolume}
	note={anyContested ? m.group_ocean_standing_note() : undefined}
	tooltip={(km3, member) => {
		const scale = earthVolume ? earthOceans(km3 / earthVolume) : null;
		return [scale, provenance(member.ocean)].filter(Boolean).join(' · ') || undefined;
	}}
/>
