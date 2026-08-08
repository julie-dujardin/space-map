<script lang="ts" module>
	import { earthRatioParts, sigFigures } from '$lib/format/quantities';
	import { ltrIsolate } from '$lib/format/bidi';

	/**
	 * How much water there is, against the only ocean anyone has a feel for.
	 *
	 * Cubic kilometres would need a unit symbol the pipeline never generates —
	 * `unit_*` labels come from Wikidata and there is no cubic-kilometre row —
	 * and "2.66×10¹⁰ km³" says less than "20× Earth's ocean" anyway. Earth is one
	 * row of eight here rather than the page's subject, so unlike everywhere else
	 * its own row prints "1×" instead of nothing: it is what the column is
	 * measured against, and a blank there would read as missing data.
	 */
	export function earthOceans(ratio: number): string {
		const parts = earthRatioParts(ratio);
		if (!parts) return ltrIsolate(`${sigFigures(1)}×`);
		return 'multiple' in parts ? `${parts.multiple}×` : parts.percent;
	}
</script>

<script lang="ts">
	import type { NotableMemberEntry } from '$lib/fetch/objects/object-data';
	import * as m from '$lib/paraglide/messages.js';
	import CountPerBodyChart, { type CountPerBodyEntry } from './CountPerBodyChart.svelte';

	interface Props {
		members: NotableMemberEntry[];
		localizedNames?: Record<string, string>;
	}
	let { members, localizedNames }: Props = $props();

	/** Earth's own, the denominator every row is quoted against. */
	const EARTH_ID = 'naif-399';

	let rows = $derived(members.filter((entry) => entry.id && entry.ocean));
	let earthVolume = $derived(
		rows.find((entry) => entry.id === EARTH_ID)?.ocean?.volume_km3 ?? null
	);

	let entries = $derived.by<CountPerBodyEntry[]>(() =>
		rows
			.map((entry) => ({
				name: localizedNames?.[entry.id ?? ''] ?? entry.name,
				primary_type: 'object' as const,
				primary_id: entry.id as string,
				color: entry.color,
				n: entry.ocean!.volume_km3
			}))
			.sort((a, b) => b.n - a.n)
	);

	// Three decades between Ganymede and Enceladus: drawn as a share of the
	// largest, six of the eight would be a sliver. A decade of headroom under
	// the smallest so its bar is still a bar.
	let scale = $derived.by(() => {
		if (!entries.length) return null;
		const low = Math.floor(Math.log10(Math.min(...entries.map((e) => e.n)))) - 1;
		const high = Math.ceil(Math.log10(Math.max(...entries.map((e) => e.n))));
		return { low, span: high - low };
	});

	function fraction(entry: CountPerBodyEntry): number {
		if (!scale) return 0;
		return Math.min(1, Math.max(0, (Math.log10(entry.n) - scale.low) / scale.span));
	}

	function text(entry: CountPerBodyEntry): string {
		return earthVolume ? earthOceans(entry.n / earthVolume) : '';
	}
</script>

{#if entries.length > 0 && earthVolume}
	<CountPerBodyChart
		{entries}
		{fraction}
		{text}
		title={m.group_ocean_volume_title()}
		hint={m.chart_log_scale()}
		tab="structure"
	/>
{/if}
