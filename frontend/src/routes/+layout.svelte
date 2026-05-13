<script lang="ts">
	import '../app.css';
	import { getLocale, getTextDirection } from '$lib/paraglide/runtime.js';
	import Sonner from '$lib/components/ui/sonner/sonner.svelte';
	import { getSettings } from '$lib/state/settings.svelte';

	let { children } = $props();
	const settings = getSettings();

	$effect(() => {
		const locale = getLocale();
		document.documentElement.lang = locale;
		document.documentElement.dir = getTextDirection(locale);
	});

	$effect(() => {
		document.documentElement.classList.toggle('dark', settings.resolvedTheme === 'dark');
	});
</script>

<Sonner position="top-right" />
{@render children()}
