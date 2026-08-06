<script lang="ts">
	import { getContext } from 'svelte';
	import type { ObjectImage } from '$lib/fetch/objects/object-data';
	import { variantUrl } from '$lib/fetch/objects/images';
	import type { AppState } from '$lib/state/app-state.svelte';
	import { imageHref, isModifiedClick } from '$lib/state/focus-link';

	interface Props {
		images: ObjectImage[];
		alt: string;
	}

	let { images, alt }: Props = $props();

	const appState = getContext<AppState>('appState');

	// Bucket pixel widths kept in sync with images.ts BUCKET_DIMS.
	const BUCKETS = { s: 512, m: 1024, xl: 4096 } as const;

	function srcsetFor(image: ObjectImage): string | undefined {
		const parts: string[] = [];
		for (const label of ['s', 'm', 'xl'] as const) {
			const url = variantUrl(image, label);
			if (url) parts.push(`${url} ${BUCKETS[label]}w`);
		}
		return parts.length ? parts.join(', ') : undefined;
	}

	function smallestUrl(image: ObjectImage): string | undefined {
		for (const label of ['s', 'm', 'xl'] as const) {
			const url = variantUrl(image, label);
			if (url) return url;
		}
		return undefined;
	}

	// Wikimedia Commons file → readable label: drop the extension and turn
	// underscores into spaces. Good enough until the exporter surfaces a
	// dedicated short title; fancier parsing belongs in the data layer, not here.
	function label(file: string): string {
		return file.replace(/\.[^.]+$/, '').replace(/_/g, ' ');
	}

	function open(e: MouseEvent, i: number) {
		if (isModifiedClick(e)) return;
		e.preventDefault();
		appState.setImage(i);
	}
</script>

<div class="gallery">
	{#each images as image, i (image.file)}
		<!-- Pinned to the Images tab rather than whatever's in view: the drawer
		     keeps every tab panel mounted, so the current tab is not this one. -->
		<a
			href={imageHref(appState, i, 'images')}
			class="tile"
			onclick={(e) => open(e, i)}
			style:aspect-ratio={image.width && image.height
				? `${image.width} / ${image.height}`
				: undefined}
		>
			<img
				src={smallestUrl(image)}
				srcset={srcsetFor(image)}
				sizes="(min-width: 768px) 180px, 45vw"
				width={image.width}
				height={image.height}
				loading="lazy"
				decoding="async"
				alt={label(image.file) || alt}
				class="tile-img"
			/>
			<span class="tile-label">{label(image.file)}</span>
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
