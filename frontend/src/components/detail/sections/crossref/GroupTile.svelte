<script lang="ts">
	import { getContext, type Snippet } from 'svelte';
	import type { AppState } from '$lib/state/app-state.svelte';
	import { applyGroup, serializeUrl } from '$lib/state/url';
	import { fetchGroupDetail } from '$lib/fetch/groups/details';
	import { pickImageUrl } from '$lib/fetch/objects/images';
	import CrossRefCard from './CrossRefCard.svelte';

	interface Props {
		/** Group slug this tile links to. */
		slug: string;
		/** Group name — the tile text and nav target. */
		name: string;
		/** Small uppercase label (the group's type). */
		label: string;
		/** Custom background, rendered instead of the group's lead image. */
		background?: Snippet;
		/** Extra classes, e.g. `col-span-2` to span a 2-col grid row. */
		class?: string;
	}
	let { slug, name, label, background, class: className }: Props = $props();

	const appState = getContext<AppState | undefined>('appState');

	// Group lead image, fetched lazily (also warms the linked page's bundle).
	// Skipped when a custom background is supplied.
	let hero = $derived.by(async () => {
		if (background) return undefined;
		const detail = await fetchGroupDetail(slug);
		const img = detail.global?.images?.[0];
		return img ? pickImageUrl(img, 300) : undefined;
	});
	let href = $derived(appState ? serializeUrl(applyGroup(appState.view, slug, name)) : undefined);
	function open(e: MouseEvent) {
		if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
		if (!appState) return;
		e.preventDefault();
		appState.setGroup(slug, name);
	}
</script>

<CrossRefCard
	{href}
	onclick={open}
	title={name}
	{hero}
	{background}
	display={name}
	{label}
	class={className}
/>
