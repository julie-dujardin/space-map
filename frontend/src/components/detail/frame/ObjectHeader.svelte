<script lang="ts">
	import type { Snippet } from 'svelte';
	import ImagesIcon from '@lucide/svelte/icons/images';
	import { Badge } from '$lib/components/ui/badge/index.js';
	import * as m from '$lib/paraglide/messages.js';
	import type { GlobalObjectData, LocalizedObjectData } from '$lib/fetch/objects/object-data';
	import { pickImageUrl } from '$lib/fetch/objects/images';
	import { formatCategory, formatObjectType } from '$lib/format/satellite';
	import { formatNumber } from '$lib/format/quantities';
	import { objectTypeLabel } from '$lib/format/object-type';
	import { isModifiedClick } from '$lib/state/focus-link';

	interface Props {
		global: GlobalObjectData | null;
		localized: LocalizedObjectData | null;
		fallbackName: string | null;
		/** The viewer, opened on the picture shown here. */
		galleryHref?: string;
		onShowGallery: () => void;
		/** Opens the images list rather than the viewer — the hero's own way into
		 *  the Images tab, which the drawer drops from its bar when it runs long. */
		listHref?: string;
		onShowList: () => void;
		/** Pictures on the whole page, across every shelf — not just the object's
		 *  own, which is all the hero itself draws from. */
		imageCount?: number;
		/** Pre-resolved badges shown before any auto-detected ones (groups use this). */
		leadingBadges?: string[];
		/** Replaces the hero image when set (e.g. the planets-category lineup). */
		hero?: Snippet;
	}

	let {
		global,
		localized,
		fallbackName,
		galleryHref,
		onShowGallery,
		listHref,
		onShowList,
		imageCount,
		leadingBadges,
		hero
	}: Props = $props();

	function showGallery(e: MouseEvent) {
		if (isModifiedClick(e)) return;
		e.preventDefault();
		onShowGallery();
	}

	function showList(e: MouseEvent) {
		if (isModifiedClick(e)) return;
		e.preventDefault();
		onShowList();
	}

	let name = $derived(localized?.name ?? global?.name ?? fallbackName ?? m.unknown());
	let images = $derived(global?.images);
	let firstImage = $derived(images?.[0]);
	// Sidebar preview is capped at max-h-48 (192 CSS px). Request ~600 device
	// px to cover the highest-DPR phones with a single bucket — pickImageUrl
	// returns `s` (512) when it exists, else the largest variant emitted.
	let imageSrc = $derived(firstImage ? pickImageUrl(firstImage, 600) : undefined);
	let celestrakBadges = $derived.by(() => {
		const ct = global?.celestrak;
		if (!ct) return null;
		const out: string[] = [];
		if (ct.object_type) out.push(formatObjectType(ct.object_type));
		for (const cat of ct.categories ?? []) out.push(formatCategory(cat));
		return out.length > 0 ? out : null;
	});
	let types = $derived(localized?.instance_of?.length ? localized.instance_of : null);
	let description = $derived(localized?.description ?? localized?.wikipedia?.description);
	let fallbackType = $derived(global?.type ? objectTypeLabel(global.type) : m.object());

	function ucfirst(s: string): string {
		return s.charAt(0).toUpperCase() + s.slice(1);
	}
</script>

<div class="flex flex-col gap-3">
	{#if hero}
		{@render hero()}
	{:else if imageSrc}
		<!-- Two destinations on one picture: the image opens the viewer, the pill
		     opens the list. The pill is hover/focus-only so it stays out of the way
		     of the picture; `hover:` is media-gated, so touch never reveals it and
		     the tab bar remains the way in there. -->
		<div class="group/hero relative overflow-hidden rounded-md">
			<a
				href={galleryHref}
				onclick={showGallery}
				aria-label={m.image_open_viewer()}
				class="block w-full cursor-zoom-in"
			>
				<img
					src={imageSrc}
					alt={name}
					loading="lazy"
					decoding="async"
					class="w-full max-h-48 object-cover"
				/>
			</a>
			<a
				href={listHref}
				onclick={showList}
				class="bg-background/85 text-foreground hover:bg-background absolute top-2 end-2 flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium opacity-0 shadow-sm backdrop-blur-sm transition-opacity group-hover/hero:opacity-100 focus-visible:opacity-100"
			>
				<ImagesIcon class="size-3.5 shrink-0" />
				{m.image_see_all()}
				<span class="text-muted-foreground">·</span>
				<span class="tabular-nums">{formatNumber(imageCount ?? images?.length ?? 0)}</span>
			</a>
		</div>
	{/if}
	<div class="flex flex-wrap items-start gap-2">
		{#if leadingBadges && leadingBadges.length > 0}
			{#each leadingBadges as b, i (i)}
				<Badge variant="secondary" class="shrink-0 text-xs">{b}</Badge>
			{/each}
		{:else if celestrakBadges}
			{#each celestrakBadges as b, i (i)}
				<Badge variant="secondary" class="shrink-0 text-xs">{b}</Badge>
			{/each}
		{:else if types}
			{#each types as t, i (i)}
				<Badge variant="secondary" class="shrink-0 text-xs">{ucfirst(t.name)}</Badge>
			{/each}
		{:else}
			<Badge variant="secondary" class="shrink-0 text-xs">{ucfirst(fallbackType)}</Badge>
		{/if}
	</div>
	{#if description}
		<p class="text-sm text-muted-foreground">{ucfirst(description)}</p>
	{/if}
</div>
