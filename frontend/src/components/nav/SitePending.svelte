<!--
  What a document page shows under its title while its payload is in flight.
  Every one of them is a lead line over a column of rows, so the blocks sit
  where the content lands and the fill-in is not read as a second reflow.
-->
<script lang="ts">
	import { Skeleton } from '$lib/components/ui/skeleton/index.js';

	interface Props {
		/** The summary line under the title; pages without one leave it off. */
		lead?: boolean;
		rows?: number;
	}

	let { lead = true, rows = 8 }: Props = $props();

	// Ragged widths, repeating: a column of equal bars reads as a table header.
	const widths = ['w-full', 'w-11/12', 'w-4/5', 'w-full', 'w-3/4'];
</script>

<div aria-hidden="true">
	{#if lead}
		<Skeleton class="-mt-6 mb-8 h-4 w-2/3 max-w-md" />
	{/if}
	<div class="flex flex-col gap-3">
		{#each { length: rows }, i (i)}
			<Skeleton class="h-6 {widths[i % widths.length]}" />
		{/each}
	</div>
</div>
