<script lang="ts">
	/** The moon lineup as lit discs, same relative sizes, no renderer behind
	 *  them. The tile is 80 px tall — a WebGL context, textures and shape models
	 *  all buy detail nothing at that size can show. */

	import { BODY_COLORS, DEFAULT_BODY_COLOR } from '$lib/constants';
	import type { LineupBody } from './BodyLineup.svelte';

	interface Props {
		bodies: LineupBody[];
	}
	let { bodies }: Props = $props();

	/** Past this the row is a strip of dots; the lineup itself pages instead. */
	const SHOWN = 5;
	/** The largest disc, sized so five of them still fit the sidebar's width. */
	const MAX_PX = 38;
	/** Below this a moon reads as grit on the tile rather than as a body. */
	const MIN_PX = 5;

	let discs = $derived.by(() => {
		const shown = bodies.slice(0, SHOWN);
		const largest = Math.max(...shown.map((body) => body.radiusKm), 0);
		if (!largest) return [];
		return shown.map((body) => {
			const color = BODY_COLORS[body.id] ?? body.color ?? DEFAULT_BODY_COLOR;
			return {
				id: body.id,
				// To scale against the largest one shown, the way the lineup is.
				size: Math.max(MIN_PX, (body.radiusKm / largest) * MAX_PX),
				// One light from the upper left, as the lineup's own is: a flat
				// circle reads as a dot, and the terminator is what makes it a body.
				fill: `radial-gradient(circle at 34% 30%, ${color}, color-mix(in srgb, ${color} 55%, #05070e) 72%, #05070e 105%)`
			};
		});
	});
</script>

<!-- Centred rather than sitting on the bottom edge: the card's caption gradient
     takes the lower third, and a row resting on it would be half swallowed. -->
<div class="flex size-full items-center justify-center gap-1.5 bg-[#05070e] px-2">
	{#each discs as disc (disc.id)}
		<div
			class="shrink-0 rounded-full"
			style:width="{disc.size}px"
			style:height="{disc.size}px"
			style:background={disc.fill}
		></div>
	{/each}
</div>
