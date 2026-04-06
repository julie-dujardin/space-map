<script lang="ts">
	import { kmToScene } from '$lib/math/units';
	import * as m from '$lib/paraglide/messages.js';

	interface Props {
		onLocate: (zoom: number) => void;
	}

	let { onLocate }: Props = $props();

	const EARTH_VIEW_DISTANCE = kmToScene(50_000);

	let state = $state<'idle' | 'loading' | 'denied'>('idle');

	function locate() {
		if (!navigator.geolocation) {
			state = 'denied';
			return;
		}
		state = 'loading';
		navigator.geolocation.getCurrentPosition(
			() => {
				state = 'idle';
				onLocate(EARTH_VIEW_DISTANCE);
			},
			(err) => {
				console.warn('Geolocation error:', err.message);
				state = err.code === err.PERMISSION_DENIED ? 'denied' : 'idle';
				// Still navigate to Earth even without precise location
				onLocate(EARTH_VIEW_DISTANCE);
			},
			{ timeout: 5000 }
		);
	}
</script>

<button
	onclick={locate}
	disabled={state === 'loading'}
	class="flex items-center justify-center w-10 h-10 rounded-full
		bg-black/50 hover:bg-black/70 backdrop-blur-sm
		text-white transition-colors cursor-pointer
		disabled:opacity-50 disabled:cursor-wait"
	title={m.my_location()}
	aria-label={m.my_location()}
>
	{#if state === 'loading'}
		<svg class="w-5 h-5 animate-spin" viewBox="0 0 24 24" fill="none">
			<circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="2" opacity="0.3" />
			<path
				d="M12 2a10 10 0 0 1 10 10"
				stroke="currentColor"
				stroke-width="2"
				stroke-linecap="round"
			/>
		</svg>
	{:else if state === 'denied'}
		<svg
			class="w-5 h-5"
			viewBox="0 0 24 24"
			fill="none"
			stroke="currentColor"
			stroke-width="2"
			stroke-linecap="round"
			stroke-linejoin="round"
		>
			<line x1="2" y1="2" x2="22" y2="22" />
			<path d="M8.7 3.4A9.96 9.96 0 0 1 12 3c2.5 0 4.8.9 6.6 2.4" />
			<path d="M3.4 8.7A10 10 0 0 0 2 12" />
			<circle cx="12" cy="12" r="2" />
		</svg>
	{:else}
		<svg
			class="w-5 h-5"
			viewBox="0 0 24 24"
			fill="none"
			stroke="currentColor"
			stroke-width="2"
			stroke-linecap="round"
			stroke-linejoin="round"
		>
			<circle cx="12" cy="12" r="3" />
			<path d="M12 2v3" />
			<path d="M12 19v3" />
			<path d="M2 12h3" />
			<path d="M19 12h3" />
			<circle cx="12" cy="12" r="8" />
		</svg>
	{/if}
</button>
