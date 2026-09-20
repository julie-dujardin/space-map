<!--
  One body's traverses as cards: the ground track on a map of the body, the
  craft that drove it, and how much there is to see. A card opens the first
  panorama of its traverse, and the arrows walk the rest.

  The gallery of every world and a single world's own page draw the same cards,
  so a reader who picks Mars from the gallery lands on more of what they clicked.
-->
<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import { panoramaHref } from '$lib/state/panorama-link';
	import { traverseYears, type Traverse } from '$lib/panorama/traverses';
	import type { LayerCredit } from '$lib/flatmap/layers';
	import PanoramaMinimap from './PanoramaMinimap.svelte';

	interface Props {
		bodyId: string;
		/** Mean radius in kilometres — the scale each map is drawn to. */
		radiusKm: number;
		traverses: Traverse[];
		/** Every author behind these maps, once each: the cards report their
		 *  layers one at a time, and the page credits what comes back. */
		onCredits?: (layers: LayerCredit[]) => void;
	}

	let { bodyId, radiusKm, traverses, onCredits }: Props = $props();

	const authors = new Map<string, LayerCredit>();

	function credit(layers: LayerCredit[]): void {
		const before = authors.size;
		for (const layer of layers)
			if (!authors.has(layer.organisation)) authors.set(layer.organisation, layer);
		// Cards share a body's maps, so all but the first usually add nothing.
		if (authors.size !== before) onCredits?.([...authors.values()]);
	}
</script>

<ul class="grid gap-4 sm:grid-cols-2">
	{#each traverses as traverse (traverse.mission)}
		<li>
			<a
				href={panoramaHref(bodyId, traverse.entries[0])}
				class="block overflow-hidden rounded-lg border border-border bg-card transition-colors hover:border-foreground/30"
			>
				<div class="relative aspect-[16/10] w-full">
					<PanoramaMinimap fill {bodyId} entries={traverse.entries} {radiusKm} onCredits={credit} />
				</div>
				<div class="flex items-baseline justify-between gap-3 px-3 py-2.5">
					<span class="font-medium">{traverse.name}</span>
					<span class="text-xs text-muted-foreground">
						{m.panorama_gallery_count({ count: traverse.entries.length })}
						· {traverseYears(traverse.entries)}
					</span>
				</div>
			</a>
		</li>
	{/each}
</ul>
