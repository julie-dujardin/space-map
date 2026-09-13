<!--
  The panorama gallery: every probe that left surface panoramas, as its
  traverse on a map of the body. A card opens the first panorama of that
  traverse.
-->
<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import PanoramaMinimap from '../../components/panorama/PanoramaMinimap.svelte';
	import SiteNav from '../../components/nav/SiteNav.svelte';
	import { bodyHref } from '$lib/state/url';
	import { panoramaHref } from '$lib/state/panorama-link';

	let { data } = $props();

	const bodies = $derived(data.bodies);

	/** The years a traverse spans, or the one year it sits in. */
	function years(entries: { time: string }[]): string {
		const start = new Date(entries[0].time).getUTCFullYear();
		const end = new Date(entries[entries.length - 1].time).getUTCFullYear();
		return start === end
			? String(start)
			: m.panorama_gallery_years({ start: String(start), end: String(end) });
	}
</script>

<svelte:head>
	<title>{m.panorama_index_title()}</title>
</svelte:head>

<div class="flex h-dvh flex-col bg-bg text-text">
	<SiteNav current="panoramas" />

	<main class="flex-1 overflow-y-auto">
		<div class="mx-auto max-w-4xl px-6 pt-10 pb-[calc(2.5rem+var(--safe-bottom))]">
			<h1 class="mb-8 text-2xl font-semibold">{m.panorama_index_title()}</h1>

			{#if data.failed}
				<p class="text-sm text-muted-foreground">{m.panorama_error()}</p>
			{:else if bodies.length === 0}
				<p class="text-sm text-muted-foreground">{m.panorama_gallery_empty()}</p>
			{/if}

			{#each bodies as body (body.id)}
				<section class="mb-10">
					<div class="mb-3 flex items-baseline justify-between gap-3">
						<h2 class="text-lg font-medium">
							<a class="hover:underline" href={bodyHref(body.id, body.name)}>{body.name}</a>
						</h2>
						<a
							class="text-sm text-muted-foreground hover:text-foreground"
							href={panoramaHref(body.id)}
						>
							{m.panorama_gallery_all()}
						</a>
					</div>
					<ul class="grid gap-4 sm:grid-cols-2">
						{#each body.traverses as traverse (traverse.mission)}
							<li>
								<a
									href={panoramaHref(body.id, traverse.entries[0])}
									class="block overflow-hidden rounded-lg border border-border bg-card transition-colors hover:border-foreground/30"
								>
									<div class="relative aspect-[16/10] w-full">
										<PanoramaMinimap
											fill
											bodyId={body.id}
											entries={traverse.entries}
											radiusKm={body.radiusKm}
										/>
									</div>
									<div class="flex items-baseline justify-between gap-3 px-3 py-2.5">
										<span class="font-medium">{traverse.name}</span>
										<span class="text-xs text-muted-foreground">
											{m.panorama_gallery_count({ count: traverse.entries.length })}
											· {years(traverse.entries)}
										</span>
									</div>
								</a>
							</li>
						{/each}
					</ul>
				</section>
			{/each}
		</div>
	</main>
</div>
