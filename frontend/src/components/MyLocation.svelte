<script lang="ts">
	import { kmToScene } from '$lib/math/units';
	import * as m from '$lib/paraglide/messages.js';
	import LocateFixedIcon from '@lucide/svelte/icons/locate-fixed';
	import LoaderCircleIcon from '@lucide/svelte/icons/loader-circle';

	interface Props {
		/** Called with zoom distance; returns animation duration in ms. */
		onLocate: (zoom: number) => number;
	}

	let { onLocate }: Props = $props();

	const EARTH_VIEW_DISTANCE = kmToScene(50_000);

	let state = $state<'idle' | 'loading'>('idle');

	function flyAndWait() {
		const durationMs = onLocate(EARTH_VIEW_DISTANCE);
		setTimeout(() => (state = 'idle'), durationMs);
	}

	function locate() {
		if (state === 'loading') return;
		state = 'loading';
		if (!navigator.geolocation) {
			flyAndWait();
			return;
		}
		navigator.geolocation.getCurrentPosition(
			() => flyAndWait(),
			(err) => {
				console.warn('Geolocation error:', err.message);
				flyAndWait();
			},
			{ timeout: 5000 }
		);
	}
</script>

<button
	onclick={locate}
	disabled={state === 'loading'}
	class="flex items-center justify-center
		w-15 h-15 md:w-10 md:h-10 rounded-full
		bg-primary-foreground hover:bg-primary-foreground/80
		text-primary transition-colors cursor-pointer
		disabled:opacity-50 disabled:cursor-wait"
	title={m.my_location()}
	aria-label={m.my_location()}
>
	{#if state === 'loading'}
		<LoaderCircleIcon class="size-7 md:size-5 animate-spin" />
	{:else}
		<LocateFixedIcon class="size-7 md:size-5" />
	{/if}
</button>
