<script lang="ts">
	import '../app.css';
	import { getLocale, getTextDirection } from '$lib/paraglide/runtime.js';
	import Sonner from '$lib/components/ui/sonner/sonner.svelte';
	import LiveAnnouncer from '$lib/a11y/LiveAnnouncer.svelte';
	import { getSettings } from '$lib/state/settings.svelte';

	let { children } = $props();
	const settings = getSettings();

	let direction = $state(getTextDirection(getLocale()));

	$effect(() => {
		const locale = getLocale();
		const dir = getTextDirection(locale);
		document.documentElement.lang = locale;
		document.documentElement.dir = dir;
		direction = dir;
	});

	$effect(() => {
		document.documentElement.classList.toggle('dark', settings.resolvedTheme === 'dark');
	});

	$effect(() => {
		document.documentElement.classList.toggle('reduce-motion', settings.resolvedReducedMotion);
	});
</script>

<Sonner position={direction === 'rtl' ? 'top-left' : 'top-right'} dir={direction} />
<LiveAnnouncer />
{@render children()}
