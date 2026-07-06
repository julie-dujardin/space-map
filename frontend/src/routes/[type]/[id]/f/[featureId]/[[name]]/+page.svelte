<script lang="ts">
	import { browser } from '$app/environment';
	import SeoHead from '$lib/seo/SeoHead.svelte';

	let { data } = $props();
</script>

{#if data.seo}
	<SeoHead seo={data.seo} />
{/if}

<!-- Client-only WebGL app; dynamic-imported so its module graph skips SSR. -->
{#if browser}
	{#await import('../../../../../../components/MapPage.svelte') then mod}
		{@const MapPage = mod.default}
		<MapPage />
	{/await}
{/if}
