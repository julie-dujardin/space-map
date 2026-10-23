<!--
  The records of an extrasolar object, one section per group of columns. The
  identifiers lead to SIMBAD, where the catalogue numbers are looked up.
-->
<script lang="ts">
	import Section from '../kit/Section.svelte';
	import Row from '../kit/Row.svelte';
	import Link from '../kit/Link.svelte';
	import type { ExtrasolarRecord } from '$lib/fetch/extrasolar/lookup';
	import { starSections } from './star-rows';

	interface Props {
		record: ExtrasolarRecord;
	}

	let { record }: Props = $props();

	let sections = $derived(starSections(record));
</script>

{#each sections as section (section.key)}
	<Section title={section.title}>
		{#each section.rows as entry, i (`${entry.label}-${i}`)}
			{#if entry.href}
				<Row label={entry.label}>
					<Link href={entry.href} external class="tabular-nums">{entry.value}</Link>
				</Row>
			{:else}
				<Row label={entry.label} value={entry.value} />
			{/if}
		{/each}
	</Section>
{/each}
