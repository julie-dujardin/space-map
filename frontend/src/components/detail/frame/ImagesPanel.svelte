<script lang="ts">
	import { imageTitle, type Gallery, type ShelfLink } from '$lib/fetch/objects/galleries';
	import type { ObjectImage } from '$lib/fetch/objects/object-data';
	import { getContext } from 'svelte';
	import * as m from '$lib/paraglide/messages.js';
	import { formatNumber } from '$lib/format/quantities';
	import type { AppState } from '$lib/state/app-state.svelte';
	import { galleryHref, isModifiedClick } from '$lib/state/focus-link';
	import Section from '../sections/kit/Section.svelte';
	import CrossRefCard from '../sections/crossref/CrossRefCard.svelte';
	import ImageGallery from './ImageGallery.svelte';
	import ImageRail from './ImageRail.svelte';

	interface Props {
		galleries: Gallery[];
		/** The open gallery; undefined shows the index of shelves. */
		active?: Gallery;
		/** The drawer title does not name the open gallery, so the panel does,
		 *  with a way back to the index. */
		headed: boolean;
		alt: string;
		/** Names a pooled picture's subject — a moon, a surface feature. */
		subjectName?: (subject: string) => string | undefined;
		/** Where the open shelf leads: the object it is about, or the tab on this
		 *  page covering the same ground. */
		shelfLink?: (gallery: Gallery) => ShelfLink | undefined;
		/** Commons filename → title in the reading language, from the localized
		 *  bundle; overrides the base-language title in the picture itself. */
		titles?: Record<string, string>;
	}

	let { galleries, active, headed, alt, subjectName, shelfLink, titles }: Props = $props();

	const appState = getContext<AppState>('appState');

	const label = (image: ObjectImage) => imageTitle(image, titles, subjectName);

	// An index of one shelf is just that shelf: most objects have nothing but
	// their own pictures, and a rail with a "see all" over them reads as a
	// detour to the same place.
	let open = $derived(active ?? (galleries.length === 1 ? galleries[0] : undefined));

	// Under the title: the object these pictures are of, or the tab that covers
	// them — either way, where the rest of this subject lives.
	let link = $derived(open ? shelfLink?.(open) : undefined);

	function follow(e: MouseEvent) {
		if (isModifiedClick(e) || !link) return;
		e.preventDefault();
		link.open();
	}

	let indexHref = $derived(galleryHref(appState, null));
	function toIndex(e: MouseEvent) {
		if (isModifiedClick(e)) return;
		e.preventDefault();
		appState.setGallery(null);
	}
</script>

{#snippet grid(shelf: Gallery)}
	<ImageGallery images={shelf.images} gallery={shelf.key} {alt} {label} />
{/snippet}

<div class="flex flex-col gap-4">
	{#if open}
		{#if link}
			<!-- Half width, in the drawer's cross-reference language: where this
			     shelf's subject is covered in full is a sideways step off the
			     gallery, not a heading over it. -->
			<div class="grid grid-cols-2">
				<CrossRefCard
					href={link.href}
					onclick={follow}
					title={link.label}
					display={link.label}
					label={link.kind}
					hero={link.hero}
					background={link.background}
				/>
			</div>
		{/if}
		<!-- A lone shelf is the index: nothing to go back to. -->
		{#if headed && galleries.length > 1}
			<Section
				title={open.title}
				titleMeta={formatNumber(open.images.length)}
				activateHref={indexHref}
				onActivate={toIndex}
				activateLabel={m.gallery_all()}
			>
				{#snippet footer()}{@render grid(open)}{/snippet}
			</Section>
		{:else}
			{@render grid(open)}
		{/if}
	{:else}
		{#each galleries as gallery (gallery.key)}
			<ImageRail
				title={gallery.title}
				images={gallery.images}
				gallery={gallery.key}
				{alt}
				{label}
			/>
		{/each}
	{/if}
</div>
