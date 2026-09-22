<!--
  The panorama gallery: every probe that left surface panoramas, as its
  traverse on a map of the body. A card opens the first panorama of that
  traverse.
-->
<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import SitePage from '../../components/nav/SitePage.svelte';
	import GalleryPending from '../../components/panorama/GalleryPending.svelte';
	import PanoramaGallery from '../../components/panorama/PanoramaGallery.svelte';
	import { streamed } from '$lib/state/streamed.svelte';
	import type { GalleryData } from './+page';

	interface Props {
		data: { gallery: Promise<GalleryData> };
	}

	let { data }: Props = $props();
	const gallery = streamed<GalleryData>(() => data.gallery);
</script>

<svelte:head>
	<title>{m.panorama_index_title()}</title>
</svelte:head>

<SitePage current="panoramas" title={m.panorama_index_title()}>
	{#if gallery.value}
		<PanoramaGallery gallery={gallery.value} />
	{:else if gallery.error}
		<p class="text-sm text-muted-foreground">{m.panorama_error()}</p>
	{:else}
		<GalleryPending />
	{/if}
</SitePage>
