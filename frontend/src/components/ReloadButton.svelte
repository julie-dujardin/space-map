<!-- Reload with feedback: the button disables and a bar runs until the page goes. -->
<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import { startPageReload } from '$lib/reload';
	import LoadingBar from './LoadingBar.svelte';

	let reloading = $state(false);
</script>

<button
	class="rounded-md bg-text px-4 py-2 text-sm font-medium text-bg hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:opacity-50"
	disabled={reloading}
	onclick={() => startPageReload(() => (reloading = true))}
>
	{m.reload()}
</button>
{#if reloading}
	<LoadingBar label={m.reload()} />
{/if}
