<script lang="ts">
	import { getContext } from 'svelte';
	import type { ObjectImage } from '$lib/fetch/objects/object-data';
	import { imageSrcset, smallestVariantUrl } from '$lib/fetch/objects/images';
	import type { AppState } from '$lib/state/app-state.svelte';
	import { imageHref, isModifiedClick } from '$lib/state/focus-link';

	interface Props {
		images: ObjectImage[];
		alt: string;
		/** Gallery key the viewer indexes into — what `&gal=` carries. */
		gallery: string;
		/** How each tile is captioned; see `imageTitle`. */
		label: (image: ObjectImage) => string;
	}

	let { images, alt, gallery, label }: Props = $props();

	const appState = getContext<AppState>('appState');

	function open(e: MouseEvent, i: number) {
		if (isModifiedClick(e)) return;
		e.preventDefault();
		appState.setImage(i, gallery);
	}
</script>

<div class="gallery">
	{#each images as image, i (image.file)}
		<a
			href={imageHref(appState, i, gallery)}
			class="tile"
			onclick={(e) => open(e, i)}
			style:aspect-ratio={image.width && image.height
				? `${image.width} / ${image.height}`
				: undefined}
		>
			<img
				src={smallestVariantUrl(image)}
				srcset={imageSrcset(image)}
				sizes="(min-width: 768px) 180px, 45vw"
				width={image.width}
				height={image.height}
				loading="lazy"
				decoding="async"
				alt={label(image) || alt}
				class="tile-img"
			/>
			<span class="tile-label">{label(image)}</span>
		</a>
	{/each}
</div>

<style>
	/* CSS columns + per-tile aspect-ratio is the universal masonry trick:
	   tiles flow into columns, and `break-inside: avoid` keeps each tile in
	   one column. Reading order is column-major (top-of-col-1, then bottom-
	   of-col-1, then top-of-col-2). For a small drawer gallery that's fine.
	   `grid-template-rows: masonry` is in the spec but not yet shippable in
	   Chrome (early 2026). */
	.gallery {
		column-count: 2;
		column-gap: 0.5rem;
	}

	.tile {
		break-inside: avoid;
		display: block;
		width: 100%;
		margin-bottom: 0.5rem;
		padding: 0;
		border: 0;
		border-radius: 6px;
		background: rgba(0, 0, 0, 0.25);
		position: relative;
		overflow: hidden;
		cursor: pointer;
	}
	.tile:focus-visible {
		outline: 2px solid var(--color-ring);
		outline-offset: 2px;
	}

	.tile-img {
		display: block;
		width: 100%;
		height: 100%;
		object-fit: cover;
	}

	.tile-label {
		position: absolute;
		inset-inline: 0;
		bottom: 0;
		padding: 1.25rem 0.625rem 0.5rem;
		font-size: 0.75rem;
		line-height: 1.2;
		color: rgba(255, 255, 255, 0.95);
		text-align: start;
		background: linear-gradient(to top, rgba(0, 0, 0, 0.7) 0%, rgba(0, 0, 0, 0) 100%);
		pointer-events: none;
	}
</style>
