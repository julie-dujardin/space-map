<script lang="ts">
	import { page } from '$app/state';
	import * as m from '$lib/paraglide/messages.js';
	import SitePage from '../components/nav/SitePage.svelte';

	const isNotFound = $derived(page.status === 404);
	const title = $derived(isNotFound ? m.error_page_404_title() : m.error_page_title());
	// 404 needs no elaboration; other errors show the real message when present.
	const message = $derived(isNotFound ? null : page.error?.message || m.error_page_body());
</script>

<svelte:head>
	<title>{title} - {m.page_title()}</title>
</svelte:head>

<!-- No `current`: the row lists no page for an error, and the site row is the
     way onward from it. -->
<SitePage {title}>
	<p class="-mt-6 text-xs text-muted-subtle tabular-nums">{page.status}</p>
	{#if message}
		<p class="mt-6 max-w-prose text-sm leading-relaxed text-muted-foreground">{message}</p>
	{/if}
</SitePage>
