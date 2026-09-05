<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import * as m from '$lib/paraglide/messages.js';
	import { randomTargetPath } from '$lib/state/random-target';
	import { uniformRandomTarget } from '$lib/state/uniform-random-target';

	// Drawn from the page rather than `load`, for the same reason as /random.
	onMount(() => {
		let left = false;
		void (async () => {
			const target = await uniformRandomTarget();
			if (left) return;
			await goto(target ? randomTargetPath(target) : '/', { replaceState: true });
		})();
		return () => (left = true);
	});
</script>

<!-- Only ever shows while the draw is in flight — longer than /random's, since
     a uniform draw downloads a slice of the catalogue to draw from. -->
<svelte:head>
	<title>{m.uniform_random_title()}</title>
	<meta name="robots" content="noindex" />
</svelte:head>

<div class="flex min-h-svh items-center justify-center bg-background text-muted-foreground">
	{m.uniform_random_loading()}
</div>
