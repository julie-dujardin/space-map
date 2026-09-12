<script lang="ts">
	/** The planetary system a body belongs to, opening its barycenter page.
	 *
	 *  The picture is the system map itself: a barycenter has no photograph, and
	 *  the map is what the page is for — the primary's limb with its moons
	 *  arrayed off it reads as "system" at tile size. */

	import CrossRefCard from './CrossRefCard.svelte';
	import PlanetarySystemMap from '../../charts/PlanetarySystemMap.svelte';
	import { focusClick, focusHref } from '$lib/state/focus-link';
	import { getContext } from 'svelte';
	import type { AppState } from '$lib/state/app-state.svelte';
	import type { FocusObject } from '$lib/state/focusable';
	import type { PlanetarySystemMapData } from '../../charts/planetary-system.svelte';
	import * as m from '$lib/paraglide/messages.js';

	interface Props {
		/** The system's barycenter id — the page this opens. */
		systemId: string;
		system: PlanetarySystemMapData;
		/** "<primary> system"; resolved by the caller off the primary's bundle. */
		name: string;
		/** Extra classes, e.g. `col-span-2` to span a 2-col grid row. */
		class?: string;
		/** The tile spans the row, so the map shows its whole axis. */
		wide?: boolean;
	}
	let { systemId, system, name, class: className, wide = false }: Props = $props();

	const appState = getContext<AppState | undefined>('appState');
	const focusObject = getContext<FocusObject | undefined>('focusObject');

	let href = $derived(focusHref(appState, systemId, name));
	let open = $derived(focusClick(focusObject, systemId, name));
</script>

<CrossRefCard
	{href}
	onclick={open}
	title={name}
	background={systemMap}
	display={name}
	label={m.moons_count_moon({ count: system.moonCount })}
	class={className}
/>

{#snippet systemMap()}
	<PlanetarySystemMap {system} ariaLabel="" variant="background" {wide} />
{/snippet}
