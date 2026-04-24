<script lang="ts">
	import { getContext } from 'svelte';
	import { Badge } from '$lib/components/ui/badge/index.js';
	import * as m from '$lib/paraglide/messages.js';
	import type { GlobalObjectData, LocalizedObjectData } from '$lib/fetch/objects/object-data';
	import { pickImageUrl } from '$lib/fetch/objects/images';
	import { formatCategory, formatObjectType } from '$lib/format/satellite';
	import type { AppState } from '$lib/state/app-state.svelte';
	import ImageViewer from '../ImageViewer.svelte';

	interface Props {
		global: GlobalObjectData | null;
		localized: LocalizedObjectData | null;
		fallbackName: string | null;
	}

	let { global, localized, fallbackName }: Props = $props();

	const appState = getContext<AppState>('appState');

	let name = $derived(localized?.name ?? global?.name ?? fallbackName ?? m.unknown());
	let images = $derived(global?.images);
	let firstImage = $derived(images?.[0]);
	// Sidebar preview is capped at max-h-48 (192 CSS px). Request ~600 device
	// px to cover the highest-DPR phones with a single bucket — pickImageUrl
	// returns `s` (512) when it exists, else the largest variant emitted.
	let imageSrc = $derived(firstImage ? pickImageUrl(firstImage, 600) : undefined);
	let viewerIndex = $derived(appState.view.imageIndex);
	let viewerOpen = $derived(
		viewerIndex !== null && !!images && images.length > 0 && viewerIndex < images.length
	);
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
	let aliases = $derived(localized?.aliases);
	let fallbackType = $derived(global?.type ? objectTypeLabel(global.type) : m.object());

	function ucfirst(s: string): string {
		return s.charAt(0).toUpperCase() + s.slice(1);
	}

	function objectTypeLabel(type: string): string {
		switch (type) {
			case 'barycenter':
				return m.type_barycenter();
			case 'lagrange_point':
				return m.type_lagrange_point();
			case 'star':
				return m.type_star();
			case 'planet':
				return m.type_planet();
			case 'dwarf_planet':
				return m.type_dwarf_planet();
			case 'moon':
				return m.type_moon();
			case 'asteroid':
			case 'asteroid_inner':
			case 'asteroid_main_belt':
			case 'asteroid_trojan':
			case 'asteroid_centaur':
			case 'asteroid_tno':
				return m.type_asteroid();
			case 'comet':
				return m.type_comet();
			case 'spacecraft':
				return m.type_spacecraft();
			case 'debris':
				return m.type_debris();
			case 'undocumented':
				return m.type_undocumented();
			default:
				return m.object();
		}
	}
</script>

<div class="flex flex-col gap-3">
	{#if imageSrc && firstImage}
		<button
			type="button"
			onclick={() => appState.setImage(0)}
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
	{#if viewerOpen && images}
		<ImageViewer {images} alt={name} onClose={() => appState.setImage(null)} />
	{/if}
	<div class="flex flex-wrap items-start gap-2">
		{#if celestrakBadges}
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
	{#if aliases && aliases.length > 0}
		<p class="text-xs text-muted-foreground">{m.also_known_as({ aliases: aliases.join(', ') })}</p>
	{/if}
</div>
