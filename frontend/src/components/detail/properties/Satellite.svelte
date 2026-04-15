<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import type { GlobalObjectData, LocalizedObjectData } from '$lib/fetch/objects/object-data';
	import { formatNumber } from '$lib/format/quantities';
	import { countryFlag, formatCountry, formatOpsStatus } from '$lib/format/satellite';
	import Section from './Section.svelte';
	import Row from './Row.svelte';
	import EntityLinks from './EntityLinks.svelte';

	interface Props {
		global: GlobalObjectData | null;
		localized: LocalizedObjectData | null;
	}

	let { global, localized }: Props = $props();

	let ct = $derived(global?.celestrak);
	let constellation = $derived(localized?.constellation);
	let countries = $derived(ct?.country_codes ?? []);

	let hasContent = $derived(
		!!ct && (constellation || countries.length > 0 || ct.ops_status || ct.rcs != null)
	);
</script>

{#if hasContent && ct}
	<Section title={m.satellite()}>
		{#if constellation}
			<Row label={m.constellation()}>
				<EntityLinks entities={[constellation]} />
			</Row>
		{/if}
		{#if ct.ops_status}
			<Row label={m.ops_status()} value={formatOpsStatus(ct.ops_status)} />
		{/if}
		{#if ct.rcs != null}
			<Row label={m.rcs()} value={`${formatNumber(ct.rcs)} m²`} tooltip={m.tooltip_rcs()} />
		{/if}
		{#if countries.length > 0}
			<Row label={countries.length === 1 ? m.country() : m.countries()}>
				<span class="flex flex-wrap justify-end gap-1.5">
					{#each countries as cc (cc)}
						<span title={cc}>{countryFlag(cc)} {formatCountry(cc)}</span>
					{/each}
				</span>
			</Row>
		{/if}
	</Section>
{/if}
