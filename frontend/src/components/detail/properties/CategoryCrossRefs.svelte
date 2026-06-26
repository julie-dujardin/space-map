<script lang="ts">
	import { getContext } from 'svelte';
	import type { AppState } from '$lib/state/app-state.svelte';
	import { applyGroup, serializeUrl } from '$lib/state/url';
	import { fetchGroupDetail } from '$lib/fetch/groups/details';
	import { pickImageUrl } from '$lib/fetch/objects/images';
	import { groupTypeLabel } from '$lib/format/group';
	import {
		CATEGORY_LABELS,
		CAT_DWARF_PLANETS,
		CAT_MOONS,
		CAT_PLANETS
	} from '$lib/fetch/groups/registry';
	import CrossRefCard from './CrossRefCard.svelte';

	interface Props {
		/** The category whose page this is; its two siblings are linked. */
		slug: string;
	}
	let { slug }: Props = $props();

	const appState = getContext<AppState | undefined>('appState');

	// The three body-collection pages cross-link to each other so a visitor on
	// one lineup can hop to the neighbouring ones.
	const SIBLINGS: Record<string, string[]> = {
		[CAT_PLANETS]: [CAT_DWARF_PLANETS, CAT_MOONS],
		[CAT_DWARF_PLANETS]: [CAT_PLANETS, CAT_MOONS],
		[CAT_MOONS]: [CAT_PLANETS, CAT_DWARF_PLANETS]
	};
	let siblings = $derived(SIBLINGS[slug] ?? []);
	const label = groupTypeLabel('category');

	// The linked category's lead image, fetched lazily (bundles are cached, so
	// this also prefetches the tile's destination page).
	async function fetchHero(s: string): Promise<string | undefined> {
		const detail = await fetchGroupDetail(s);
		const img = detail.global?.images?.[0];
		return img ? pickImageUrl(img, 300) : undefined;
	}
	let tiles = $derived(
		siblings.map((s) => ({ slug: s, name: CATEGORY_LABELS[s] ?? s, hero: fetchHero(s) }))
	);

	function href(s: string, name: string): string | undefined {
		if (!appState) return undefined;
		return serializeUrl(applyGroup(appState.view, s, name));
	}

	function open(e: MouseEvent, s: string, name: string) {
		if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
		if (!appState) return;
		e.preventDefault();
		appState.setGroup(s, name);
	}
</script>

{#if tiles.length > 0}
	<div class="grid grid-cols-2 gap-2">
		{#each tiles as t (t.slug)}
			<CrossRefCard
				href={href(t.slug, t.name)}
				onclick={(e) => open(e, t.slug, t.name)}
				title={t.name}
				hero={t.hero}
				display={t.name}
				{label}
			/>
		{/each}
	</div>
{/if}
