<script lang="ts">
	// A planetary system's cross-refs are the parts of that system: the primary
	// itself, then the pages its own contents live on — the moon list and the ring
	// catalogue, both hosted on the primary. The barycenter carries none of them.
	// A system too small for a moon list tiles its moons one by one instead.
	import BodyTile from './BodyTile.svelte';
	import RingSystemTile from './RingSystemTile.svelte';
	import MoonDiscRow from '../../charts/MoonDiscRow.svelte';
	import type { LineupBody } from '../../charts/BodyLineup.svelte';
	import * as m from '$lib/paraglide/messages.js';

	interface Props {
		/** The system's primary — its own page, and the host of every part below. */
		primaryId: string;
		primaryName: string;
		/** Whether the primary has a Moons tab to open. Systems whose moons all fit
		 *  the overview strip have none, so the tile would lead nowhere. */
		hasMoons: boolean;
		/** The moons themselves, drawn on that tile instead of the primary's photo. */
		moonDiscs: LineupBody[];
		/** Whether the primary has a named-ring catalogue behind its Rings tab. */
		hasRings: boolean;
	}
	let { primaryId, primaryName, hasMoons, moonDiscs, hasRings }: Props = $props();

	// The primary takes the whole first row — it is the system's subject, and the
	// rest are parts of it, paired up below; an odd last tile widens rather than
	// dangling at half width.
	let parts = $derived((hasMoons ? 1 : moonDiscs.length) + (hasRings ? 1 : 0));
	let wideIndex = $derived(parts % 2 === 1 ? parts - 1 : -1);
	function span(i: number): string {
		return i === wideIndex ? 'col-span-2' : '';
	}
</script>

<div class="grid grid-cols-2 gap-2">
	<BodyTile id={primaryId} name={primaryName} class="col-span-2" />
	{#if hasMoons}
		<BodyTile
			id={primaryId}
			name={primaryName}
			label={m.tab_moons()}
			tab="members"
			background={moonDiscs.length ? moonRow : undefined}
			class={span(0)}
		/>
	{:else}
		{#each moonDiscs as moon, i (moon.id)}
			<BodyTile id={moon.id} name={moon.name} class={span(i)} />
		{/each}
	{/if}
	{#if hasRings}
		<RingSystemTile id={primaryId} name={primaryName} class={span(parts - 1)} />
	{/if}
</div>

{#snippet moonRow()}
	<MoonDiscRow bodies={moonDiscs} />
{/snippet}
