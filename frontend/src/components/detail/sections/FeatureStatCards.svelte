<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import * as Tooltip from '$lib/components/ui/tooltip/index.js';
	import type { NomenclatureFeature } from '$lib/fetch/nomenclature/fetch';
	import type { FeatureDetailData } from '$lib/fetch/nomenclature/details';
	import { formatQuantity } from '$lib/format/quantities';

	interface Props {
		feature: NomenclatureFeature;
		detail: FeatureDetailData | null;
	}
	let { feature, detail }: Props = $props();

	interface Stat {
		label: string;
		value: string;
		tooltip?: string;
	}

	// How big, how deep or tall, when it was named. Coordinates stay a property
	// row below: they place the feature, they don't describe it. Wikidata length
	// is skipped when it only restates the IAU diameter (Valles Marineris:
	// 3761 km across, 3770 km long), and area entirely — four features have one
	// and the values are unreliable.
	let stats = $derived.by<Stat[]>(() => {
		const out: Stat[] = [];
		const diameterM = feature.diameterM;
		if (diameterM > 0)
			out.push({
				label: m.diameter(),
				// The gazetteer spans metre-wide landing stones to 11 000 km rift
				// systems; metres stop meaning anything past a kilometre.
				value:
					diameterM >= 1000
						? formatQuantity({ value: diameterM / 1000, unit: 'kilometre' }, true)
						: formatQuantity({ value: diameterM, unit: 'metre' }, true)
			});

		const wd = detail?.global?.wikidata;
		const depth = wd?.vertical_depth;
		const height = wd?.height ?? wd?.elevation;
		const length = wd?.length;
		if (depth) out.push({ label: m.feature_depth(), value: formatQuantity(depth, true) });
		else if (height) out.push({ label: m.feature_height(), value: formatQuantity(height, true) });
		else if (length && !restatesDiameter(length.value, length.unit, diameterM))
			out.push({ label: m.property_name_length(), value: formatQuantity(length, true) });

		const approval = detail?.global?.approval_date;
		if (approval) {
			// Pre-digital IAU rows are year-only, stamped 1 January; 49 of the 57
			// type pages inherit such a date. Only the year is real.
			const year = approval.slice(0, 4);
			if (/^\d{4}$/.test(year)) out.push({ label: m.feature_named_date(), value: year });
		}
		return out;
	});

	function restatesDiameter(value: number, unit: string, diameterM: number): boolean {
		if (!diameterM) return false;
		const metres = unit === 'kilometre' ? value * 1000 : unit === 'metre' ? value : null;
		if (metres == null) return false;
		return Math.abs(metres - diameterM) / diameterM < 0.1;
	}
</script>

{#if stats.length > 0}
	<div class="grid auto-cols-fr grid-flow-col gap-2">
		{#each stats as s (s.label)}
			<div
				class="border-border/60 bg-muted/40 flex flex-col gap-1 rounded-md border p-2.5 {s.tooltip
					? 'cursor-help'
					: ''}"
			>
				<div class="text-muted-foreground text-[10px] uppercase">{s.label}</div>
				{#if s.tooltip}
					<Tooltip.Root>
						<Tooltip.Trigger>
							{#snippet child({ props })}
								<div class="text-sm font-semibold tabular-nums" {...props}>{s.value}</div>
							{/snippet}
						</Tooltip.Trigger>
						<Tooltip.Content>{s.tooltip}</Tooltip.Content>
					</Tooltip.Root>
				{:else}
					<div class="text-sm font-semibold tabular-nums">{s.value}</div>
				{/if}
			</div>
		{/each}
	</div>
{/if}
