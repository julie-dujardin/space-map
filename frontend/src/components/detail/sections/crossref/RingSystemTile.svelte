<script lang="ts">
	/** One ringed body on the Ring Systems page, opening its Rings tab.
	 *
	 *  The backdrop is always the ring plane, never a photograph: every picture
	 *  that exists is of the planet wearing the rings, and half the eight have
	 *  none at all. The photographs live in this page's Images tab instead,
	 *  drawn from the "Rings of X" articles. */

	import * as m from '$lib/paraglide/messages.js';
	import { fetchObjectDetail, type GlobalObjectData } from '$lib/fetch/objects/object-data';
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

	let ringCount = $derived(
		Object.values(global?.ring_features ?? {}).filter((f) => f.kind === 'ring').length
	);
</script>

<BodyTile
	{id}
	{name}
	tab="rings"
	background={stripBar}
	label={ringCount ? m.rings_count_ring({ count: ringCount }) : m.tab_rings()}
	class={className}
/>

{#snippet stripBar()}
	<RingStripBar bodyId={id} />
{/snippet}
