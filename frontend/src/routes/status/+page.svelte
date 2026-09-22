<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import SitePage from '../../components/nav/SitePage.svelte';
	import SitePending from '../../components/nav/SitePending.svelte';
	import StatusReport from '../../components/status/StatusReport.svelte';
	import { streamed } from '$lib/state/streamed.svelte';
	import type { Status } from '$lib/status/status-payload';

	interface Props {
		data: { status: Promise<Status> };
	}

	let { data }: Props = $props();
	const status = streamed<Status>(() => data.status);
</script>

<svelte:head>
	<title>{m.status_page_title()} - {m.page_title()}</title>
</svelte:head>

<SitePage current="status" title={m.status_page_title()}>
	{#if status.value}
		<StatusReport status={status.value} />
	{:else if status.error}
		<p class="text-sm text-muted-foreground">{m.detail_error_body()}</p>
	{:else}
		<SitePending rows={10} />
	{/if}
</SitePage>
