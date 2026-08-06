<script lang="ts">
	/** The Rings tab's hero: the best picture of the ring system, selected from
	 *  the "Rings of X" article the panel already cites. Credit and license ride
	 *  in the viewer it opens, the same way the overview hero's do. */

	import { getContext } from 'svelte';
	import ImagesIcon from '@lucide/svelte/icons/images';
	import * as m from '$lib/paraglide/messages.js';
	import type { ObjectImage } from '$lib/fetch/objects/object-data';
	import { variantUrl } from '$lib/fetch/objects/images';
	import { RINGS_GALLERY } from '$lib/fetch/objects/galleries';
	import { formatNumber } from '$lib/format/quantities';
	import type { AppState } from '$lib/state/app-state.svelte';
	import { galleryHref, imageHref, isModifiedClick } from '$lib/state/focus-link';

	interface Props {
		/** The ring system's pictures; the first is the hero, the rest are one
		 *  click away in the Images tab. */
		images: ObjectImage[];
		alt: string;
	}

	let { images, alt }: Props = $props();

	const appState = getContext<AppState>('appState');

	let image = $derived(images[0]);

	function showViewer(e: MouseEvent) {
		if (isModifiedClick(e)) return;
		e.preventDefault();
		appState.setImage(0, RINGS_GALLERY);
	}

	function showGallery(e: MouseEvent) {
		if (isModifiedClick(e)) return;
		e.preventDefault();
		appState.setGallery(RINGS_GALLERY);
	}

	/** The two widths the drawer can ask for; the source is far larger than the
	 *  panel and the small variant alone blurs on a retina screen. */
	let srcset = $derived(
		(['s', 'm'] as const)
			.map((label) => {
				const url = variantUrl(image, label);
				return url ? `${url} ${label === 's' ? 512 : 1024}w` : null;
			})
			.filter((part) => part !== null)
			.join(', ')
	);
</script>

<!-- Same hover affordance as the overview hero: the picture opens the viewer,
     the pill opens the shelf the rest of them sit on. -->
<div class="group/hero relative overflow-hidden rounded-md">
	<!-- Contained rather than cropped: these run from a 2.4:1 Cassini mosaic to
	     a square JWST frame, and filling the box would cut the rings out of the
	     tall ones. The black backdrop is the sky the pictures are already mostly
	     made of, so the letterboxing doesn't read as a gap. -->
	<a
		href={imageHref(appState, 0, RINGS_GALLERY)}
		onclick={showViewer}
		aria-label={m.image_open_viewer()}
		class="block w-full cursor-zoom-in"
	>
		<img
			src={variantUrl(image, 's')}
			{srcset}
			sizes="(min-width: 768px) 350px, 90vw"
			width={image.width}
			height={image.height}
			{alt}
			loading="lazy"
			decoding="async"
			class="max-h-52 w-full rounded-md bg-black/40 object-contain"
		/>
	</a>
	{#if images.length > 1}
		<a
			href={galleryHref(appState, RINGS_GALLERY)}
			onclick={showGallery}
			class="bg-background/85 text-foreground hover:bg-background absolute top-2 end-2 flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium opacity-0 shadow-sm backdrop-blur-sm transition-opacity group-hover/hero:opacity-100 focus-visible:opacity-100"
		>
			<ImagesIcon class="size-3.5 shrink-0" />
			{m.image_see_all()}
			<span class="text-muted-foreground">·</span>
			<span class="tabular-nums">{formatNumber(images.length)}</span>
		</a>
	{/if}
</div>
