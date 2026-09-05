<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import * as m from '$lib/paraglide/messages.js';
	import { randomTarget, randomTargetPath } from '$lib/state/random-target';

	// Drawn from the page rather than `load`: the walk goes through the client
	// fetch layer, which SvelteKit flags when a `load` uses it. Replacing the
	// history entry keeps Back from landing on the redirect.
	onMount(() => {
		let left = false;
		void (async () => {
			const target = await randomTarget();
			if (left) return;
			// Nothing drawn means the data tree never answered; the default view is
			// where a reader with no destination belongs.
			await goto(target ? randomTargetPath(target) : '/', { replaceState: true });
		})();
		return () => (left = true);
	});
</script>

<!-- Only ever shows while the walk is in flight. Never a search result: the
     page is a different one every time. -->
<svelte:head>
	<title>{m.random_title()}</title>
	<meta name="robots" content="noindex" />
</svelte:head>

<div class="flex min-h-svh items-center justify-center bg-background text-muted-foreground">
	{m.random_loading()}
</div>
