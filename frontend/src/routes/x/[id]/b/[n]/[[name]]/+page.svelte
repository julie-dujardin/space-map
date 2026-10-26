<script lang="ts">
	import { browser } from '$app/environment';
	import SeoHead from '$lib/seo/SeoHead.svelte';
	import MapPageLoader from '../../../../../../components/MapPageLoader.svelte';

	let { data } = $props();
</script>

<!-- Server-rendered meta for crawlers and first paint; null on client navigation
     (MapPage takes over the <title> then). -->
{#if data.seo}
	<SeoHead seo={data.seo} />
{/if}

<!-- The WebGL app is client-only. -->
{#if browser}
	<MapPageLoader />
{/if}
