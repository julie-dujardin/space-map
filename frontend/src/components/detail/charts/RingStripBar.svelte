<script lang="ts">
	/** A body's rings drawn edge-on across the full width, with no axis and no
	 *  labels — the tile backdrop for a system nobody has photographed. */

	import { fetchObjectDetail } from '$lib/fetch/objects/object-data';
	import { loadRingStrips } from '$lib/rings/strip';
	import { paintRingBar } from '$lib/rings/strip-bar';

	interface Props {
		bodyId: string;
	}
	let { bodyId }: Props = $props();

	let bar = $state<string | null>(null);
	$effect(() => {
		const body = bodyId;
		bar = null;
		let live = true;
		// The catalogue alongside the rendered profiles: the box filter averages a
		// narrow ring into the empty space around it, and the marks it earns come
		// from the catalogued optical depths.
		Promise.all([loadRingStrips(body), fetchObjectDetail(body)])
			.then(([profiles, detail]) => {
				if (live) bar = paintRingBar(profiles, detail.global?.ring_features);
			})
			.catch((error) => console.warn(`Ring bar for ${body} unavailable:`, error));
		return () => {
			live = false;
		};
	});
</script>

<!-- Its own near-black backdrop rather than the card's: the rings are pale and
     faint, and on the light theme's muted grey they would not read at all. -->
<div class="size-full bg-[#05070e]">
	{#if bar}
		<img src={bar} alt="" class="size-full object-fill" />
	{/if}
</div>
