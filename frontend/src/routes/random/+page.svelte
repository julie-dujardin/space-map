<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
</script>

<!-- The load redirects, so this only ever shows while the walk is in flight.
     Never a search result: the page is a different one every time. -->
<svelte:head>
	<title>{m.random_title()}</title>
	<meta name="robots" content="noindex" />
</svelte:head>

<div class="flex min-h-svh items-center justify-center bg-background text-muted-foreground">
	{m.random_loading()}
</div>
