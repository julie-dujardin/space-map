<script lang="ts">
	import { getContext } from 'svelte';
	import * as m from '$lib/paraglide/messages.js';
	import type { ObjectImage } from '$lib/fetch/objects/object-data';
	import { imageSrcset, smallestVariantUrl } from '$lib/fetch/objects/images';
	import { formatNumber } from '$lib/format/quantities';
	import type { AppState } from '$lib/state/app-state.svelte';
	import { galleryHref, imageHref, isModifiedClick } from '$lib/state/focus-link';
	import Section from '../sections/kit/Section.svelte';

	interface Props {
		title: string;
		images: ObjectImage[];
		/** Gallery key this rail scrolls through — what `&gal=` carries. */
		gallery: string;
		alt: string;
		/** How each tile is captioned; see `imageTitle`. */
		label: (image: ObjectImage) => string;
	}

	let { title, images, gallery, alt, label }: Props = $props();

	const appState = getContext<AppState>('appState');

	// A taste of the shelf; the gallery itself holds the rest.
	const RAIL_LIMIT = 6;
	let shown = $derived(images.slice(0, RAIL_LIMIT));
	let href = $derived(galleryHref(appState, gallery));

	function open(e: MouseEvent, i: number) {
		if (isModifiedClick(e)) return;
		e.preventDefault();
		appState.setImage(i, gallery);
	}

	function seeAll(e: MouseEvent) {
		if (isModifiedClick(e)) return;
		e.preventDefault();
		appState.setGallery(gallery);
	}
</script>

<Section
	{title}
	titleMeta={formatNumber(images.length)}
	titleHref={href}
	activateHref={href}
	onActivate={seeAll}
	activateLabel={m.gallery_see_all()}
>
	{#snippet footer()}
		<!-- Scrolls sideways rather than wrapping: a rail is a peek at the shelf, and
		     the row keeps every gallery's heading a fixed distance apart. -->
		<div class="no-scrollbar flex snap-x snap-mandatory gap-2 overflow-x-auto">
			{#each shown as image, i (image.file)}
				<a
					href={imageHref(appState, i, gallery)}
					onclick={(e) => open(e, i)}
					class="focus-visible:ring-ring relative h-28 shrink-0 snap-start overflow-hidden rounded-md bg-black/25 focus-visible:ring-2 focus-visible:outline-none"
					style:aspect-ratio={image.width && image.height
						? `${image.width} / ${image.height}`
						: '4 / 3'}
				>
					<img
						src={smallestVariantUrl(image)}
						srcset={imageSrcset(image)}
						sizes="240px"
						loading="lazy"
						decoding="async"
						alt={label(image) || alt}
						class="h-full w-full object-cover"
					/>
				</a>
			{/each}
		</div>
	{/snippet}
</Section>
