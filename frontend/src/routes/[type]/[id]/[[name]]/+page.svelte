<script lang="ts">
	import { browser } from '$app/environment';
	import SeoHead from '$lib/seo/SeoHead.svelte';

	let { data } = $props();
</script>

<!-- Server-rendered meta for crawlers/first paint; null on client navigation
     (MapPage takes over the <title> then). -->
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
