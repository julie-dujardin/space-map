<script lang="ts">
	/** The Planetary Systems page's membership: one full-width tile per system,
	 *  each drawn as its own map — the same picture the system page heroes. */

	import { untrack } from 'svelte';
	import type { NotableMemberEntry } from '$lib/fetch/objects/object-data';
	import {
		fetchPlanetarySystemsMap,
		type PlanetarySystemsMapFile
	} from '$lib/fetch/groups/planetary-systems-map';
	import { systemFromMapEntry } from '../../charts/planetary-system.svelte';
	import SystemTile from './SystemTile.svelte';

	interface Props {
		members: NotableMemberEntry[];
		/** Member id → "<primary> system"; the entry's own name is the primary's. */
		localizedNames?: Record<string, string>;
	}
	let { members, localizedNames }: Props = $props();

	let maps = $state<PlanetarySystemsMapFile | null>(null);
	$effect(() => {
		untrack(() =>
			fetchPlanetarySystemsMap()
				.then((f) => (maps = f))
				.catch((e) => console.error('Planetary systems map failed to load', e))
		);
	});

	let tiles = $derived(
		members.flatMap((entry) => {
			const map = entry.id ? maps?.[entry.id] : undefined;
			if (!entry.id || !map) return [];
			const name = localizedNames?.[entry.id] ?? entry.name;
			return [{ id: entry.id, name, system: systemFromMapEntry(map, name) }];
		})
	);
</script>

{#if tiles.length > 0}
	<div class="grid gap-2">
		{#each tiles as t (t.id)}
			<SystemTile systemId={t.id} system={t.system} name={t.name} wide />
		{/each}
	</div>
{/if}
