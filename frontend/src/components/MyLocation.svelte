<script lang="ts">
	import { kmToScene } from '$lib/math/units';
	import * as m from '$lib/paraglide/messages.js';
	import LocateFixedIcon from '@lucide/svelte/icons/locate-fixed';
	import LoaderCircleIcon from '@lucide/svelte/icons/loader-circle';
	import { toast } from 'svelte-sonner';

	interface Props {
		/** Called with zoom distance and optional geolocation; returns animation duration in ms. */
		onLocate: (zoom: number, latitude?: number, longitude?: number) => number;
	}

	let { onLocate }: Props = $props();

	const EARTH_VIEW_DISTANCE = kmToScene(50_000);

	let state = $state<'idle' | 'loading'>('idle');
	let inaccurateWarned = false;

	const CLOSE_VIEW_DISTANCE = 0.001;
	/** Above this reported accuracy (in meters) we warn the user — geo-IP
	 *  sources love to claim ~25 km accuracy when they're really off by 100s. */
	const INACCURATE_THRESHOLD_M = 5_000;
	/** Reuse a cached fix up to this old (10 min) before re-querying. */
	const MAX_AGE_MS = 10 * 60 * 1000;

	function flyAndWait(latitude?: number, longitude?: number) {
		const zoom = latitude !== undefined ? CLOSE_VIEW_DISTANCE : EARTH_VIEW_DISTANCE;
		const durationMs = onLocate(zoom, latitude, longitude);
		setTimeout(() => (state = 'idle'), durationMs);
	}

	function locate() {
		if (state === 'loading') return;
		state = 'loading';
		if (!navigator.geolocation) {
			toast.error(m.my_location_error());
			flyAndWait();
			return;
		}
		navigator.geolocation.getCurrentPosition(
			(pos) => {
				const { latitude, longitude, accuracy } = pos.coords;
				if (accuracy > INACCURATE_THRESHOLD_M && !inaccurateWarned) {
					inaccurateWarned = true;
					toast.warning(m.my_location_inaccurate({ km: Math.round(accuracy / 1000) }));
				}
				flyAndWait(latitude, longitude);
			},
			(err) => {
				console.warn('Geolocation error:', err.message);
				toast.error(m.my_location_error(), { description: err.message });
				flyAndWait();
			},
			{ timeout: 5000, enableHighAccuracy: true, maximumAge: MAX_AGE_MS }
		);
	}
</script>

<button
	onclick={locate}
	disabled={state === 'loading'}
	class="pointer-events-auto flex items-center justify-center
		w-12 h-12 md:w-10 md:h-10 rounded-full
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
