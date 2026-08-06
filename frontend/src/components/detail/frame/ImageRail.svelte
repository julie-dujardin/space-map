<script lang="ts">
	import { getContext } from 'svelte';
	import ChevronRightIcon from '@lucide/svelte/icons/chevron-right';
	import * as m from '$lib/paraglide/messages.js';
	import type { ObjectImage } from '$lib/fetch/objects/object-data';
	import { imageLabel, imageSrcset, smallestVariantUrl } from '$lib/fetch/objects/images';
	import type { AppState } from '$lib/state/app-state.svelte';
	import { galleryHref, imageHref, isModifiedClick } from '$lib/state/focus-link';

	interface Props {
		title: string;
		images: ObjectImage[];
		/** Gallery key this rail scrolls through — what `&gal=` carries. */
		gallery: string;
		alt: string;
		subjectName?: (subject: string) => string | undefined;
	}

	let { title, images, gallery, alt, subjectName }: Props = $props();

	const appState = getContext<AppState>('appState');

	// A taste of the shelf; the gallery itself holds the rest.
	const RAIL_LIMIT = 6;
	let shown = $derived(images.slice(0, RAIL_LIMIT));

	function label(image: ObjectImage): string {
		const named = image.subject === undefined ? undefined : subjectName?.(String(image.subject));
		return named ?? imageLabel(image.file);
	}

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

<section class="flex flex-col gap-2">
	<div class="flex items-baseline justify-between gap-2 px-1">
		<h3 class="flex items-baseline gap-2 text-sm font-medium">
			{title}
			<span class="text-muted-foreground text-xs tabular-nums">{images.length}</span>
		</h3>
		<a
			href={galleryHref(appState, gallery)}
			onclick={seeAll}
			class="text-muted-foreground hover:text-foreground focus-visible:ring-ring flex shrink-0 items-center gap-0.5 rounded-sm text-xs focus-visible:ring-2 focus-visible:outline-none"
		>
			{m.gallery_see_all()}
			<ChevronRightIcon class="size-3 rtl:rotate-180" />
		</a>
	</div>
	<!-- Scrolls sideways rather than wrapping: a rail is a peek at the shelf, and
	     the row keeps every gallery's heading a fixed distance apart. -->
	<div class="no-scrollbar flex snap-x snap-mandatory gap-2 overflow-x-auto px-1">
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
</section>
