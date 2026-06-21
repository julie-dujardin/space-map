<script lang="ts">
	import { getContext } from 'svelte';
	import * as m from '$lib/paraglide/messages.js';
	import type { AppState } from '$lib/state/app-state.svelte';
	import { applyGroup, serializeUrl } from '$lib/state/url';
	import { CLASS_SLUG_PREFIX, orbitClassLabel } from '$lib/charts/orbit-zones';
	import { fetchGroupDetail } from '$lib/fetch/groups/details';
	import { pickImageUrl } from '$lib/fetch/objects/images';

	interface Props {
		/** SBDB OrbitClass enum name (e.g. "MBA") — its `class-<NAME>` group. */
		className: string;
	}
	let { className }: Props = $props();

	const appState = getContext<AppState | undefined>('appState');

	let slug = $derived(`${CLASS_SLUG_PREFIX}${className}`);
	let name = $derived(orbitClassLabel(className));
	let href = $derived(appState ? serializeUrl(applyGroup(appState.view, slug, name)) : undefined);

	// Hero matches the group page's lead image; fetched lazily (the bundle is
	// cached and prefetches the group page this chip links to).
	let thumb = $derived.by(async () => {
		const detail = await fetchGroupDetail(slug);
		const img = detail.global?.images?.[0];
		return img ? pickImageUrl(img, 96) : undefined;
	});

	function open(e: MouseEvent) {
		if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
		if (!appState) return;
		e.preventDefault();
		appState.setGroup(slug, name);
	}
</script>

<a
	{href}
	onclick={open}
	class="border-border/60 bg-muted/40 hover:bg-muted/70 pointer-events-auto flex items-center gap-3 rounded-md border p-2.5"
>
	{#await thumb then src}
		{#if src}
			<img
				{src}
				alt=""
				loading="lazy"
				decoding="async"
				class="bg-muted size-12 shrink-0 rounded-lg object-cover"
			/>
		{/if}
	{/await}
	<div class="flex min-w-0 flex-col gap-0.5">
		<span class="text-muted-foreground text-[10px] uppercase">{m.group()}</span>
		<span class="truncate text-sm font-medium">{name}</span>
	</div>
</a>
