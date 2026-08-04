<script lang="ts">
	/** One ringed body on the Ring Systems page, opening its Rings tab.
	 *
	 *  The picture is of the rings, never the body's own portrait. Where the
	 *  ring article has none — or where the one it has is a poor view of them,
	 *  see `TILE_PICTURE` — the ring plane stands in, drawn from the same
	 *  profiles the chart uses. */

	import * as m from '$lib/paraglide/messages.js';
	import { fetchObjectDetail, type GlobalObjectData } from '$lib/fetch/objects/object-data';
	import { pickImageUrl } from '$lib/fetch/objects/images';
	import RingStripBar from '../../charts/RingStripBar.svelte';
	import BodyTile from './BodyTile.svelte';

	interface Props {
		/** Backend object id of the ringed body. */
		id: string;
		name: string;
		/** Extra classes, e.g. `col-span-2` to span a 2-col grid row. */
		class?: string;
	}
	let { id, name, class: className }: Props = $props();

	// The same cached bundle BodyTile reads for the destination page.
	let global = $state<GlobalObjectData | null>(null);
	$effect(() => {
		const body = id;
		global = null;
		let live = true;
		fetchObjectDetail(body).then((detail) => {
			if (live) global = detail.global ?? null;
		});
		return () => {
			live = false;
		};
	});

	/** What a tile shows, where availability alone gets it wrong. `photo` and
	 *  `plane` force one or the other; a body absent here takes the photograph
	 *  when its ring article has one and the ring plane otherwise. Kept here
	 *  rather than in the export: it is a judgement about one picture, and it
	 *  changes when someone uploads a better one. */
	const TILE_PICTURE: Record<string, 'photo' | 'plane'> = {
		// Chariklo's article leads on a light curve — the trace of the occultation
		// its rings were found in. It is the evidence for them, not a view of them.
		'spkid-20010199': 'plane'
	};

	let available = $derived(global?.ring_images?.[0]);
	/** Null until the bundle lands, so a photographed system never flashes the
	 *  plane and then swaps it out. A forced `photo` still falls back where the
	 *  body has no picture — the override states a preference, not a promise. */
	let picture = $derived.by<'photo' | 'plane' | null>(() => {
		if (!global) return null;
		if (TILE_PICTURE[id] === 'plane' || !available) return 'plane';
		return 'photo';
	});
	let hero = $derived(picture === 'photo' && available ? pickImageUrl(available, 300) : undefined);
	let ringCount = $derived(
		Object.values(global?.ring_features ?? {}).filter((f) => f.kind === 'ring').length
	);
</script>

<BodyTile
	{id}
	{name}
	tab="rings"
	{hero}
	background={picture === 'plane' ? stripBar : undefined}
	label={ringCount ? m.rings_count_ring({ count: ringCount }) : m.tab_rings()}
	class={className}
/>

{#snippet stripBar()}
	<RingStripBar bodyId={id} />
{/snippet}
