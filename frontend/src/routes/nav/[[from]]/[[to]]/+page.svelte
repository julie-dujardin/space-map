<script lang="ts">
	import { browser } from '$app/environment';
	import SeoHead from '$lib/seo/SeoHead.svelte';

	let { data } = $props();
</script>

<!-- Every pair of bodies is a URL, so the route is a crawl trap with nothing
     indexable in it — both ends already have their own pages. -->
<svelte:head>
	<meta name="robots" content="noindex, follow" />
</svelte:head>

{#if data.seo}
	<SeoHead seo={data.seo} />
{/if}

<!-- The WebGL app is client-only. Dynamic-import it so its Three.js module graph
     never loads during SSR — the server emits just the head + shell. -->
{#if browser}
	{#await import('../../../../components/MapPage.svelte') then mod}
		{@const MapPage = mod.default}
		<MapPage />
	{/await}
{/if}
