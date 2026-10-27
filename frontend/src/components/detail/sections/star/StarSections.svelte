<!-- An extrasolar object's values, grouped by meaning. -->
<script lang="ts">
	import Section from '../kit/Section.svelte';
	import Row from '../kit/Row.svelte';
	import Link from '../kit/Link.svelte';
	import EntityLinks from '../kit/EntityLinks.svelte';
	import * as m from '$lib/paraglide/messages.js';
	import type { ExtrasolarRecord } from '$lib/fetch/extrasolar/lookup';
	import type { LocalizedObjectData } from '$lib/fetch/objects/object-data';
	import { starSections } from './star-rows';

	interface Props {
		record: ExtrasolarRecord;
		localized: LocalizedObjectData | null;
	}

	let { record, localized }: Props = $props();

	let sections = $derived(starSections(record));
</script>

{#each sections as section (section.key)}
	<Section title={section.title}>
		{#if section.key === 'position' && localized?.iau_constellation}
			<Row label={m.star_constellation()}>
				<EntityLinks entities={[localized.iau_constellation]} />
			</Row>
		{/if}
		{#each section.rows as entry, i (`${entry.label}-${i}`)}
			{#if entry.href}
				<Row label={entry.label}>
					<Link href={entry.href} external class="tabular-nums">{entry.value}</Link>
				</Row>
			{:else}
				<Row label={entry.label} value={entry.value} valueTooltip={entry.tooltip} />
			{/if}
		{/each}
	</Section>
{/each}
