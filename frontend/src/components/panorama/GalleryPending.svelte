<!--
  What the gallery shows while its index is in flight: the summary line, then
  a world's heading over the card grid the traverses land in — each block the
  card's own map and caption, so the fill-in is not read as a second reflow.
-->
<script lang="ts">
	import { Skeleton } from '$lib/components/ui/skeleton/index.js';
</script>

<div aria-hidden="true">
	<Skeleton class="-mt-6 mb-8 h-4 w-80 max-w-full" />
	{#each { length: 2 }, section (section)}
		<section class="mb-10">
			<Skeleton class="mb-3 h-6 w-28" />
			<div class="grid gap-4 sm:grid-cols-2">
				{#each { length: 2 }, card (card)}
					<div class="overflow-hidden rounded-lg border border-border">
						<Skeleton class="aspect-[16/10] w-full rounded-none" />
						<div class="px-3 py-2.5"><Skeleton class="h-5 w-32" /></div>
					</div>
				{/each}
			</div>
		</section>
	{/each}
</div>
