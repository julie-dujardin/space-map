<script lang="ts">
	/** The ring system seen edge-on. The scale starts at the body's centre rather
	 *  than at the inner edge, so the rings sit where they really are and the gap
	 *  between planet and rings is drawn to the same scale as the rings. */

	import type { RingFeature } from '$lib/fetch/objects/object-data';
	import { loadRingStrips } from '$lib/rings/strip';
	import { paintRingBar } from '$lib/rings/strip-bar';
	import type { RingBarWindow } from '$lib/rings/overview-bar';

	interface Props {
		features: Record<string, RingFeature>;
		window: RingBarWindow;
		bodyId: string;
	}

	let { features, window: win, bodyId }: Props = $props();

	const HEIGHT = 20;
	/** Room past the outer edge, so the outermost ring stops short of the frame
	 *  rather than reading as a bar that ran out of width. */
	const TAIL = 10;

	let bar = $state<string | null>(null);

	$effect(() => {
		const body = bodyId;
		const drawn = [win.inner, win.outer] as const;
		bar = null;
		let live = true;
		loadRingStrips(body)
			.then((profiles) => {
				if (live) bar = paintRingBar(profiles, features, drawn);
			})
			.catch((error) => console.warn(`Ring bar for ${body} unavailable:`, error));
		return () => {
			live = false;
		};
	});

	// The plotted span is the width less a fixed tail, so the two edges fall out
	// of the ratios without measuring the element.
	let span = $derived(`calc(100% - ${TAIL}px)`);
</script>

<!-- Near-black rather than the card's background: the rings are pale and faint,
     and on the light theme's muted grey they would not read at all. LTR because
     the bar is a radius that grows away from the planet, not a line of text. -->
<div dir="ltr" class="relative overflow-hidden rounded-sm bg-[#05070e]" style="height: {HEIGHT}px">
	{#if bar}
		<img
			src={bar}
			alt=""
			class="absolute top-0 h-full object-fill"
			style="left: calc({span} * {win.inner / win.outer}); width: calc({span} * {(win.outer -
				win.inner) /
				win.outer})"
		/>
	{/if}
</div>
