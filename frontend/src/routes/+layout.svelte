<script lang="ts">
	import '../app.css';
	import { getLocale, getTextDirection } from '$lib/paraglide/runtime.js';
	import Sonner from '$lib/components/ui/sonner/sonner.svelte';

	let { children } = $props();

	$effect(() => {
		const locale = getLocale();
		document.documentElement.lang = locale;
		document.documentElement.dir = getTextDirection(locale);
	});
</script>

<Sonner position="top-right" />
{@render children()}
