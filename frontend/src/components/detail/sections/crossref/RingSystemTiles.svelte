<script lang="ts">
	/** The Ring Systems page's membership: one tile per ringed body, in the
	 *  catalogue's order (the four giants outward, then the small bodies). */

	import type { NotableMemberEntry } from '$lib/fetch/objects/object-data';
	import RingSystemTile from './RingSystemTile.svelte';

	interface Props {
		members: NotableMemberEntry[];
		localizedNames?: Record<string, string>;
	}
	let { members, localizedNames }: Props = $props();

	let tiles = $derived(members.filter((entry) => entry.id));
	// An odd count leaves the last tile alone on its row — widen it rather than
	// letting it sit half-width. Mirrors CategoryChildTiles.
	let wideIndex = $derived(tiles.length % 2 === 1 ? tiles.length - 1 : -1);
</script>

{#if tiles.length > 0}
	<div class="grid grid-cols-2 gap-2">
		{#each tiles as entry, i (entry.id)}
			<RingSystemTile
				id={entry.id ?? ''}
				name={localizedNames?.[entry.id ?? ''] ?? entry.name}
				class={i === wideIndex ? 'col-span-2' : ''}
			/>
		{/each}
	</div>
{/if}
