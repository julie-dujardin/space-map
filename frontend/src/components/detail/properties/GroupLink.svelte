<script lang="ts">
	import { getContext } from 'svelte';
	import * as m from '$lib/paraglide/messages.js';
	import type { AppState } from '$lib/state/app-state.svelte';
	import { applyGroup, serializeUrl } from '$lib/state/url';
	import { CLASS_SLUG_PREFIX, orbitClassLabel } from '$lib/charts/orbit-zones';
	import { fetchGroupDetail } from '$lib/fetch/groups/details';
	import { pickImageUrl } from '$lib/fetch/objects/images';
	import CrossRefCard from './CrossRefCard.svelte';

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
	let hero = $derived.by(async () => {
		const detail = await fetchGroupDetail(slug);
		const img = detail.global?.images?.[0];
		return img ? pickImageUrl(img, 300) : undefined;
	});

	function open(e: MouseEvent) {
		if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
		if (!appState) return;
		e.preventDefault();
		appState.setGroup(slug, name);
	}
</script>

<CrossRefCard {href} onclick={open} title={name} {hero} display={name} label={m.group()} />
