<script lang="ts">
	import { getContext } from 'svelte';
	import * as m from '$lib/paraglide/messages.js';
	import type { FragmentOf } from '$lib/fetch/objects/object-data';
	import { pickedThumbnailUrl, pickImageUrl } from '$lib/fetch/objects/images';
	import { fetchGroupDetail } from '$lib/fetch/groups/details';
	import type { AppState } from '$lib/state/app-state.svelte';
	import type { FocusObject } from '$lib/state/focusable';
	import { focusClick, focusHref, groupClick, groupHref } from '$lib/state/focus-link';
	import CrossRefCard from './crossref/CrossRefCard.svelte';

	interface Props {
		fragmentOf: FragmentOf;
	}
	let { fragmentOf }: Props = $props();

	const appState = getContext<AppState | undefined>('appState');
	const focusObject = getContext<FocusObject | undefined>('focusObject');

	let isGroup = $derived(fragmentOf.primary_type === 'group');
	let href = $derived(
		isGroup
			? groupHref(appState, fragmentOf.primary_id, fragmentOf.name)
			: focusHref(appState, fragmentOf.primary_id, fragmentOf.name)
	);

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

	// Parent comet's mesh isn't worth flying to — just select it.
	let open = $derived(
		isGroup
			? groupClick(appState, fragmentOf.primary_id, fragmentOf.name)
			: focusClick(focusObject, fragmentOf.primary_id, fragmentOf.name, { moveCamera: false })
	);
</script>

<CrossRefCard
	{href}
	onclick={open}
	title={fragmentOf.name}
	{hero}
	display={fragmentOf.name}
	label={m.fragment_of()}
/>
