<!-- An extrasolar object's values, grouped by meaning. -->
<script lang="ts">
	import Section from '../kit/Section.svelte';
	import Row from '../kit/Row.svelte';
	import Link from '../kit/Link.svelte';
	import EntityLinks from '../kit/EntityLinks.svelte';
	import type { StarSection } from './star-rows';

	interface Props {
		sections: StarSection[];
	}

	let { sections }: Props = $props();
</script>

{#each sections as section (section.key)}
	<Section title={section.title}>
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
