<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import SitePage from '../../components/nav/SitePage.svelte';
	import SitePending from '../../components/nav/SitePending.svelte';
	import { SITE_GUTTER } from '../../components/nav/site';
	import SubwayMapPage from '../../components/nav/SubwayMapPage.svelte';
	import { streamed } from '$lib/state/streamed.svelte';
	import type { SubwayPageData } from './+page';

	interface Props {
		data: { subway: Promise<SubwayPageData> };
	}

	let { data }: Props = $props();
	const subway = streamed<SubwayPageData>(() => data.subway);
</script>

<svelte:head>
	<title>{m.nav_delta_v()} - {m.page_title()}</title>
</svelte:head>

<!-- Bleeding, so the strip gets the whole width; everything else guttered. -->
<SitePage current="nav" title={m.nav_delta_v()} bleed>
	{#if subway.value}
		<SubwayMapPage data={subway.value} />
	{:else if subway.error}
		<p class="{SITE_GUTTER} text-sm text-muted-foreground">{m.delta_v_error()}</p>
	{:else}
		<div class={SITE_GUTTER}><SitePending lead={false} rows={7} /></div>
	{/if}
</SitePage>
