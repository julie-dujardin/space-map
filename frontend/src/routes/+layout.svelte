<script lang="ts">
	import '../app.css';
	import faviconLight from '$lib/assets/favicon-light.svg';
	import faviconDark from '$lib/assets/favicon-dark.svg';
	import { getLocale, getTextDirection } from '$lib/paraglide/runtime.js';
	import Sonner from '$lib/components/ui/sonner/sonner.svelte';

	let { children } = $props();

	$effect(() => {
		const locale = getLocale();
		document.documentElement.lang = locale;
		document.documentElement.dir = getTextDirection(locale);
	});
</script>

<svelte:head>
	<link rel="icon" media="(prefers-color-scheme: dark)" href={faviconDark} />
	<link rel="icon" media="(prefers-color-scheme: light)" href={faviconLight} />
</svelte:head>

<Sonner position="top-right" />
{@render children()}
