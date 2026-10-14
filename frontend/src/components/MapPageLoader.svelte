<!--
  The WebGL app. A dynamic import keeps its Three.js module graph out of SSR,
  so the server emits only the head and the shell.
-->
<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import { importWithRetry } from '$lib/lazy-import';
	import ReloadButton from './ReloadButton.svelte';

	/** The first attempt failed; a retry may still load it. */
	let failed = $state(false);
	const mapPage = importWithRetry(
		() => import('./MapPage.svelte'),
		() => (failed = true)
	);
</script>

{#snippet failure()}
	<div
		role="alert"
		class="flex h-screen flex-col items-center justify-center gap-4 bg-bg px-6 text-center"
	>
		<p class="max-w-md text-sm text-text-error">{m.map_load_failed()}</p>
		<ReloadButton />
	</div>
{/snippet}

{#await mapPage}
	{#if failed}
		{@render failure()}
	{/if}
{:then mod}
	{@const MapPage = mod.default}
	<MapPage />
{:catch}
	{@render failure()}
{/await}
