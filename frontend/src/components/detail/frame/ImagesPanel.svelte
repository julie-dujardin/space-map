<script lang="ts">
	import { getContext } from 'svelte';
	import ArrowRightIcon from '@lucide/svelte/icons/arrow-right';
	import { imageTitle, type Gallery } from '$lib/fetch/objects/galleries';
	import type { ObjectImage } from '$lib/fetch/objects/object-data';
	import type { AppState } from '$lib/state/app-state.svelte';
	import type { FocusObject } from '$lib/state/focusable';
	import { focusHref, isModifiedClick } from '$lib/state/focus-link';
	import ImageGallery from './ImageGallery.svelte';
	import ImageRail from './ImageRail.svelte';

	interface Props {
		galleries: Gallery[];
		/** The open gallery; undefined shows the index of shelves. */
		active?: Gallery;
		alt: string;
		/** Names a pooled picture's subject — a moon, a surface feature. */
		subjectName?: (subject: string) => string | undefined;
		/** Commons filename → title in the reading language, from the localized
		 *  bundle; overrides the base-language title in the picture itself. */
		titles?: Record<string, string>;
	}

	let { galleries, active, alt, subjectName, titles }: Props = $props();

	const label = (image: ObjectImage) => imageTitle(image, titles, subjectName);

	const appState = getContext<AppState>('appState');
	const focusObject = getContext<FocusObject | undefined>('focusObject');

	// An index of one shelf is just that shelf: most objects have nothing but
	// their own pictures, and a rail with a "see all" over them reads as a
	// detour to the same place.
	let open = $derived(active ?? (galleries.length === 1 ? galleries[0] : undefined));

	// A shelf about one object says so under its title: the pictures are of it,
	// and its own page is where the rest of them live.
	let subject = $derived(open?.subjectId);
	let subjectLabel = $derived(subject ? (subjectName?.(subject) ?? open?.title) : undefined);

	function goToSubject(e: MouseEvent) {
		if (isModifiedClick(e) || !focusObject || !subject) return;
		e.preventDefault();
		focusObject(subject, subjectLabel ?? '', { moveCamera: false });
	}
</script>

<div class="flex flex-col gap-4 p-1">
	{#if open}
		{#if subject}
			<a
				href={focusHref(appState, subject, subjectLabel ?? '')}
				onclick={goToSubject}
				class="text-muted-foreground hover:text-foreground focus-visible:ring-ring flex w-fit items-center gap-1 rounded-sm px-1 text-xs focus-visible:ring-2 focus-visible:outline-none"
			>
				{subjectLabel}
				<ArrowRightIcon class="size-3 rtl:rotate-180" />
			</a>
		{/if}
		<ImageGallery images={open.images} gallery={open.key} {alt} {label} />
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
