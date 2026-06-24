<script lang="ts">
	import { getContext } from 'svelte';
	import * as m from '$lib/paraglide/messages.js';
	import type { FragmentOf } from '$lib/fetch/objects/object-data';
	import { pickedThumbnailUrl, pickImageUrl } from '$lib/fetch/objects/images';
	import { fetchGroupDetail } from '$lib/fetch/groups/details';
	import type { AppState } from '$lib/state/app-state.svelte';
	import type { FocusObject } from '$lib/state/focusable';
	import { applyFocus, applyGroup, serializeUrl, urlTypeFromId } from '$lib/state/url';
	import CrossRefCard from './CrossRefCard.svelte';

	interface Props {
		fragmentOf: FragmentOf;
	}
	let { fragmentOf }: Props = $props();

	const appState = getContext<AppState | undefined>('appState');
	const focusObject = getContext<FocusObject | undefined>('focusObject');

	let href = $derived.by(() => {
		if (!appState) return undefined;
		const { name, primary_type, primary_id } = fragmentOf;
		return primary_type === 'group'
			? serializeUrl(applyGroup(appState.view, primary_id, name))
			: serializeUrl(
					applyFocus(appState.view, { type: urlTypeFromId(primary_id), id: primary_id, name })
				);
	});

	// The parent comet's own thumbnail; a split-comet group falls back to its lead image.
	let hero = $derived.by<string | Promise<string | undefined> | undefined>(() => {
		if (fragmentOf.thumbnail) return pickedThumbnailUrl(fragmentOf.thumbnail);
		if (fragmentOf.primary_type === 'group')
			return fetchGroupDetail(fragmentOf.primary_id).then((d) => {
				const img = d.global?.images?.[0];
				return img ? pickImageUrl(img, 300) : undefined;
			});
		return undefined;
	});

	function open(e: MouseEvent) {
		if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
		const { name, primary_type, primary_id } = fragmentOf;
		if (primary_type === 'group') {
			if (!appState) return;
			e.preventDefault();
			appState.setGroup(primary_id, name);
			return;
		}
		if (!focusObject) return;
		e.preventDefault();
		// Parent comet's mesh isn't worth flying to — just select it.
		focusObject(primary_id, name, { moveCamera: false });
	}
</script>

<CrossRefCard
	{href}
	onclick={open}
	title={fragmentOf.name}
	{hero}
	display={fragmentOf.name}
	label={m.fragment_of()}
/>
