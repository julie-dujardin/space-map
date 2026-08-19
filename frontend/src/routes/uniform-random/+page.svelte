<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
</script>

<!-- The load redirects, so this only ever shows while the draw is in flight —
     longer than /random's, since a uniform draw downloads a slice of the
     catalogue to draw from. -->
<svelte:head>
	<title>{m.uniform_random_title()}</title>
	<meta name="robots" content="noindex" />
</svelte:head>

<div class="flex min-h-svh items-center justify-center bg-background text-muted-foreground">
	{m.uniform_random_loading()}
</div>
