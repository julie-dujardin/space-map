<!-- An extrasolar object's values, grouped by meaning. -->
<script lang="ts">
	import Section from '../kit/Section.svelte';
	import Row from '../kit/Row.svelte';
	import Link from '../kit/Link.svelte';
	import EntityLinks from '../kit/EntityLinks.svelte';
	import * as m from '$lib/paraglide/messages.js';
	import type { LocalizedObjectData } from '$lib/fetch/objects/object-data';
	import type { StarSection } from './star-rows';

	interface Props {
		sections: StarSection[];
		localized: LocalizedObjectData | null;
	}

	let { sections, localized }: Props = $props();
</script>

{#each sections as section (section.key)}
	<Section title={section.title}>
		{#if section.key === 'position' && localized?.iau_constellation}
			<Row label={m.star_constellation()}>
				<EntityLinks entities={[localized.iau_constellation]} />
			</Row>
		{/if}
		{#each section.rows as entry, i (`${entry.label}-${i}`)}
			{#if entry.entities}
				<Row label={entry.label}>
					<EntityLinks entities={entry.entities} />
				</Row>
			{:else if entry.href}
				<Row label={entry.label}>
					<Link href={entry.href} external class="tabular-nums">{entry.value}</Link>
				</Row>
			{:else}
				<Row
					label={entry.label}
					value={entry.value}
					tooltip={entry.definition}
					valueTooltip={entry.tooltip}
					note={entry.note}
				/>
			{/if}
		{/each}
	</Section>
{/each}
