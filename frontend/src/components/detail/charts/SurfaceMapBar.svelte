<script lang="ts">
	/** A body's global map, filling the frame with nothing drawn on it — the tile
	 *  backdrop for the Surface tab, which opens on the same texture under its
	 *  chart grid. */

	import { versionedUrl } from '$lib/fetch/data-base';

	interface Props {
		bodyId: string;
	}
	let { bodyId }: Props = $props();

	let failed = $state(false);
	let mapUrl = $derived(versionedUrl(`/v1/textures/${bodyId}/low.webp`, 'textures'));
	$effect(() => {
		void bodyId;
		failed = false;
	});
</script>

<div class="size-full bg-[#05070e]">
	{#if !failed}
		<!-- Cropped rather than fitted: the tile is wider than the 2:1 map, and
		     letterboxing a texture reads as a missing picture. -->
		<img
			src={mapUrl}
			alt=""
			loading="lazy"
			decoding="async"
			onerror={() => (failed = true)}
			class="size-full object-cover"
		/>
	{/if}
</div>
