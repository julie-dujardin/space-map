<script lang="ts">
	import { getContext, type Snippet } from 'svelte';
	import type { AppState } from '$lib/state/app-state.svelte';
	import type { FocusObject } from '$lib/state/focusable';
	import type { DrawerTab } from '$lib/state/view';
	import { applyFocus, serializeUrl, urlTypeFromId } from '$lib/state/url';
	import { fetchObjectDetail } from '$lib/fetch/objects/object-data';
	import { pickImageUrl } from '$lib/fetch/objects/images';
	import { objectTypeLabel } from '$lib/format/object-type';
	import CrossRefCard from './CrossRefCard.svelte';

	interface Props {
		/** Backend object id (e.g. `naif-399`) this tile links to. */
		id: string;
		/** Tile name; the object's own name is fetched when omitted. */
		name?: string;
		/** Small uppercase label; the object's type is fetched when omitted. */
		label?: string;
		/** Open the linked body on this tab (e.g. `members` for a moon list). */
		tab?: Exclude<DrawerTab, 'overview'>;
		/** Custom backdrop, rendered instead of the object's lead image — for a
		 *  tile about one aspect of the body, which its portrait doesn't show. */
		background?: Snippet;
		/** Extra classes, e.g. `col-span-2` to span a 2-col grid row. */
		class?: string;
	}
	let { id, name, label, tab, background, class: className }: Props = $props();

	const appState = getContext<AppState | undefined>('appState');
	// Scene-aware focus: selects the body in the renderer so the drawer follows.
	// `setFocus` alone only rewrites the URL, leaving the scene on the old body.
	const focusObject = getContext<FocusObject | undefined>('focusObject');

	// One cached bundle fetch backs the name, label and hero (also warms the
	// destination page).
	let detail = $derived(fetchObjectDetail(id));
	let hero = $derived(
		detail.then((d) => {
			const img = d.global?.images?.[0];
			return img ? pickImageUrl(img, 300) : undefined;
		})
	);
	// Name/label from the bundle, fetched only when the caller didn't supply them.
	let fetched = $state<{ name: string; label: string } | null>(null);
	$effect(() => {
		if (name && label) return;
		let cancelled = false;
		detail.then((d) => {
			if (cancelled) return;
			fetched = {
				name: d.localized?.name ?? d.global?.name ?? '',
				label: d.global?.type ? objectTypeLabel(d.global.type) : ''
			};
		});
		return () => {
			cancelled = true;
		};
	});
	let resolvedName = $derived(name ?? fetched?.name ?? '');
	let resolvedLabel = $derived(label ?? fetched?.label ?? '');

	let href = $derived(
		appState
			? serializeUrl(
					applyFocus(appState.view, { type: urlTypeFromId(id), id, name: resolvedName, tab })
				)
			: undefined
	);
	function open(e: MouseEvent) {
		if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
		if (!focusObject) return; // fall back to the href's native navigation
		e.preventDefault();
		focusObject(id, resolvedName, { tab });
	}
</script>

<CrossRefCard
	{href}
	onclick={open}
	title={resolvedName}
	{hero}
	{background}
	display={resolvedName}
	label={resolvedLabel}
	class={className}
/>
