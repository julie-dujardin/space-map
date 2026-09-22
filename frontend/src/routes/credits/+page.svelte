<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import SitePage from '../../components/nav/SitePage.svelte';
	import SitePending from '../../components/nav/SitePending.svelte';
	import CreditList from '../../components/credits/CreditList.svelte';
	import { streamed } from '$lib/state/streamed.svelte';
	import type { Credits } from '$lib/credits/credits-payload';

	interface Props {
		data: { credits: Promise<Credits> };
	}

	let { data }: Props = $props();
	const credits = streamed<Credits>(() => data.credits);
</script>

<svelte:head>
	<title>{m.credits_page_title()} - {m.page_title()}</title>
</svelte:head>

<SitePage current="credits" title={m.credits_page_title()}>
	{#if credits.value}
		<CreditList credits={credits.value} />
	{:else if credits.error}
		<p class="text-sm text-muted-foreground">{m.detail_error_body()}</p>
	{:else}
		<SitePending lead={false} rows={12} />
	{/if}
</SitePage>
