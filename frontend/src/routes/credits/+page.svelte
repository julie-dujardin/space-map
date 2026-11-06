<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import SitePage from '../../components/nav/SitePage.svelte';
	import SitePending from '../../components/nav/SitePending.svelte';
	import CreditList from '../../components/credits/CreditList.svelte';
	import { streamed } from '$lib/state/streamed.svelte';
	import type { Credits } from '$lib/credits/credits-payload';
	import type { ExtrasolarCredit } from '$lib/fetch/extrasolar/files';
	import { fetchStarCatalogueCredits } from '$lib/credits/star-sources';
	import { fetchNestCredits } from '$lib/scene/dust/nest';

	interface Props {
		data: { credits: Promise<Credits> };
	}

	let { data }: Props = $props();
	const credits = streamed<Credits>(() => data.credits);
	// The star catalogues and the dust credit themselves in their exports' metadata.
	const starCredits = Promise.all([fetchStarCatalogueCredits(), fetchNestCredits()]).then((lists) =>
		lists.flat()
	);
	const stars = streamed<ExtrasolarCredit[]>(() => starCredits);
</script>

<svelte:head>
	<title>{m.credits_page_title()} - {m.page_title()}</title>
</svelte:head>

<SitePage current="credits" title={m.credits_page_title()}>
	{#if credits.value}
		<CreditList credits={credits.value} stars={stars.value ?? []} />
	{:else if credits.error}
		<p class="text-sm text-muted-foreground">{m.detail_error_body()}</p>
	{:else}
		<SitePending lead={false} rows={12} />
	{/if}
</SitePage>
