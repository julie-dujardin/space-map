<script lang="ts">
	import type { Snippet } from 'svelte';
	import { Badge } from '$lib/components/ui/badge/index.js';
	import * as m from '$lib/paraglide/messages.js';
	import type { GlobalObjectData, LocalizedObjectData } from '$lib/fetch/objects/object-data';
	import { pickImageUrl } from '$lib/fetch/objects/images';
	import { formatCategory, formatObjectType } from '$lib/format/satellite';
	import { objectTypeLabel } from '$lib/format/object-type';

	interface Props {
		global: GlobalObjectData | null;
		localized: LocalizedObjectData | null;
		fallbackName: string | null;
		onShowGallery: () => void;
		/** Pre-resolved badges shown before any auto-detected ones (groups use this). */
		leadingBadges?: string[];
		/** Replaces the hero image when set (e.g. the planets-category lineup). */
		hero?: Snippet;
	}

	let { global, localized, fallbackName, onShowGallery, leadingBadges, hero }: Props = $props();

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
		<button
			type="button"
			onclick={onShowGallery}
			aria-label={m.image_open_viewer()}
			class="cursor-zoom-in overflow-hidden rounded-md"
		>
			<img
				src={imageSrc}
				alt={name}
				loading="lazy"
				decoding="async"
				class="w-full max-h-48 object-cover"
			/>
		</button>
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
