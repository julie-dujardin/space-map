<script lang="ts">
	import { page } from '$app/state';
	import * as m from '$lib/paraglide/messages.js';

	const isNotFound = $derived(page.status === 404);
	const title = $derived(isNotFound ? m.error_page_404_title() : m.error_page_title());
	// 404 needs no elaboration; other errors show the real message when present.
	const message = $derived(isNotFound ? null : page.error?.message || m.error_page_body());
</script>

<div
	class="flex h-screen w-full flex-col items-center justify-center gap-4 bg-bg px-6 text-center text-text"
>
	<p class="text-4xl font-bold tabular-nums">{page.status}</p>
	<h1 class="text-lg font-semibold">{title}</h1>
	{#if message}
		<p class="max-w-md text-sm text-muted-foreground">{message}</p>
	{/if}
	<a
		href="/"
		class="mt-2 rounded-md bg-text px-4 py-2 text-sm font-medium text-bg hover:opacity-90"
	>
		{m.error_go_home()}
	</a>
</div>
