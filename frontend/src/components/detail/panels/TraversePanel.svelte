<!--
  A rover's own surface panoramas: the best-covered sweep of each stretch of
  the mission, each one a way into the viewer at that spot.
-->
<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import { versionedUrl } from '$lib/fetch/data-base';
	import { formatIsoDate } from '$lib/format/date';
	import { panoramaHref } from '$lib/state/panorama-link';
	import type { Traverse } from '../state/traverse-state.svelte';

	interface Props {
		traverse: Traverse;
	}

	let { traverse }: Props = $props();

	/** The years the traverse spans, or the one year it sits in. */
	let years = $derived.by(() => {
		const { entries } = traverse;
		const start = new Date(entries[0].time).getUTCFullYear();
		const end = new Date(entries[entries.length - 1].time).getUTCFullYear();
		return start === end
			? String(start)
			: m.panorama_gallery_years({ start: String(start), end: String(end) });
	});
</script>

<div class="flex flex-col gap-4 px-4 pb-4">
	<!-- The tab is already titled Surface and the hero is already the traverse;
	     all the line has left to say is how much of it there is. -->
	<p class="text-xs text-muted-foreground">
		{m.panorama_gallery_count({ count: traverse.entries.length })} · {years}
	</p>

	<ul class="grid gap-3 sm:grid-cols-2">
		{#each traverse.highlights as entry (entry.id)}
			<li>
				<a
					href={panoramaHref(traverse.bodyId, entry)}
					class="flex h-full flex-col overflow-hidden rounded-lg border border-border bg-card transition-colors hover:border-foreground/30"
				>
					<!-- The preview is the observed strip alone, so its aspect varies with
					     how much sky the sweep caught; the box crops rather than letting
					     the grid step. -->
					<img
						src={versionedUrl(`/v1/panoramas/${entry.id}-preview.webp`, 'panoramas')}
						alt={entry.title ?? ''}
						loading="lazy"
						class="h-24 w-full bg-black/40 object-cover"
					/>
					<!-- The clock time of a mosaic that took twenty minutes says nothing a
					     card needs, so the caption dates it to the day. -->
					<div class="flex flex-1 items-baseline justify-between gap-2 px-3 py-2">
						{#if entry.sol !== undefined}
							<span class="text-sm font-medium whitespace-nowrap">
								{m.panorama_sol({ sol: entry.sol })}
							</span>
						{/if}
						<span class="text-end text-xs leading-tight text-muted-foreground">
							{formatIsoDate(entry.time.slice(0, 10))}
						</span>
					</div>
				</a>
			</li>
		{/each}
	</ul>
</div>
