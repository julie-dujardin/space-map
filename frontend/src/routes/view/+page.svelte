<!--
  The panorama gallery: every probe that left surface panoramas, as its
  traverse on a map of the body. A card opens the first panorama of that
  traverse.
-->
<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import TraverseCards from '../../components/panorama/TraverseCards.svelte';
	import MapCredits from '../../components/panorama/MapCredits.svelte';
	import SitePage from '../../components/nav/SitePage.svelte';
	import { panoramaHref } from '$lib/state/panorama-link';
	import { getLocale } from '$lib/paraglide/runtime';
	import type { LayerCredit } from '$lib/flatmap/layers';

	let { data } = $props();

	const bodies = $derived(data.bodies);

	/** What each body's maps are drawn from, as the minimaps report it. */
	let mapCredits = $state<Record<string, LayerCredit[]>>({});

	/** Every map author on the page once, in body order. */
	const credits = $derived.by(() => {
		const out = new Map<string, LayerCredit>();
		for (const body of bodies)
			for (const credit of mapCredits[body.id] ?? [])
				if (!out.has(credit.organisation)) out.set(credit.organisation, credit);
		return [...out.values()];
	});

	/** What the gallery holds, as one line: panoramas, the craft that took them,
	 *  and the worlds they stand on. */
	const summary = $derived.by(() => {
		// The plural form is chosen on the number, the text shows the grouped one.
		const n = (count: number) => ({ count, display: count.toLocaleString(getLocale()) });
		return m.panorama_gallery_summary({
			panoramas: m.panorama_gallery_summary_panoramas(n(data.summary.panoramas)),
			probes: m.panorama_gallery_summary_probes(n(data.summary.probes)),
			worlds: m.panorama_gallery_summary_worlds(n(data.summary.worlds))
		});
	});
</script>

<svelte:head>
	<title>{m.panorama_index_title()}</title>
</svelte:head>

<SitePage current="panoramas" title={m.panorama_index_title()}>
	{#if data.failed}
		<p class="text-sm text-muted-foreground">{m.panorama_error()}</p>
	{:else if bodies.length === 0}
		<p class="text-sm text-muted-foreground">{m.panorama_gallery_empty()}</p>
	{:else}
		<p class="-mt-6 mb-8 text-sm text-muted-foreground">{summary}</p>
	{/if}

	{#each bodies as body (body.id)}
		<section class="mb-10">
			<h2 class="mb-3 text-lg font-medium">
				<a class="hover:underline" href={panoramaHref(body.id)}>{body.name}</a>
			</h2>
			<TraverseCards
				bodyId={body.id}
				radiusKm={body.radiusKm}
				traverses={body.traverses}
				onCredits={(layers) => (mapCredits[body.id] = layers)}
			/>
		</section>
	{/each}

	<MapCredits {credits} />
</SitePage>
