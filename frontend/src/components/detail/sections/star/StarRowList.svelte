<!-- Rows of an extrasolar object's values, in a section's list. -->
<script lang="ts">
	import Row from '../kit/Row.svelte';
	import Link from '../kit/Link.svelte';
	import EntityLinks from '../kit/EntityLinks.svelte';
	import type { StarRowEntry } from './star-rows';

	interface Props {
		rows: StarRowEntry[];
	}

	let { rows }: Props = $props();
</script>

{#each rows as entry, i (`${entry.label}-${i}`)}
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
