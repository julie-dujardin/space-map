<script lang="ts">
	import StatCard, { type Stat, type StatSize } from './StatCard.svelte';

	interface Props {
		/** Fewer than three is normal, not a gap — the row does not pad itself. */
		stats: Stat[];
		size?: StatSize;
	}

	let { stats, size = 'md' }: Props = $props();
</script>

{#if stats.length > 0}
	<div class="grid auto-cols-fr grid-flow-col gap-2">
		{#each stats as stat (stat.label)}
			<StatCard {stat} {size} />
		{/each}
	</div>
{/if}
