<!-- A planet's published properties, grouped by meaning. -->
<script lang="ts">
	import Section from '../kit/Section.svelte';
	import Row from '../kit/Row.svelte';
	import Link from '../kit/Link.svelte';
	import type { PlanetSection } from './planet-rows';

	interface Props {
		sections: PlanetSection[];
	}

	let { sections }: Props = $props();
</script>

{#each sections as section (section.key)}
	<Section title={section.title}>
		{#each section.rows as entry, i (`${entry.label}-${i}`)}
			{#if entry.href}
				<Row label={entry.label} note={entry.note} labelIsName={entry.labelIsName}>
					<Link href={entry.href} external>{entry.value}</Link>
				</Row>
			{:else}
				<Row
					label={entry.label}
					value={entry.value}
					tooltip={entry.definition}
					valueTooltip={entry.tooltip}
					note={entry.note}
					labelIsName={entry.labelIsName}
				/>
			{/if}
		{/each}
	</Section>
{/each}
