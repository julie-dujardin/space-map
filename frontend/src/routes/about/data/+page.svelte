<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import SitePage from '../../../components/nav/SitePage.svelte';
	import SitePending from '../../../components/nav/SitePending.svelte';
	import DataReport from '../../../components/about/DataReport.svelte';
	import { streamed } from '$lib/state/streamed.svelte';
	import type { AboutData } from '$lib/about/data-payload';

	interface Props {
		data: { report: Promise<AboutData> };
	}

	let { data }: Props = $props();
	const report = streamed<AboutData>(() => data.report);
</script>

<svelte:head>
	<title>{m.about_data_page_title()} - {m.page_title()}</title>
</svelte:head>

<SitePage current="data" title={m.about_data_page_title()}>
	{#if report.value}
		<DataReport data={report.value} />
	{:else if report.error}
		<p class="text-sm text-muted-foreground">{m.detail_error_body()}</p>
	{:else}
		<SitePending rows={12} />
	{/if}
</SitePage>
