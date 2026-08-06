<script lang="ts" module>
	import type { AtmosphereBlock } from '$lib/fetch/objects/object-data';

	type Composition = NonNullable<AtmosphereBlock['composition']>;

	/**
	 * Everything the bar shows is a share of the species we list, so a body
	 * whose sources only pin one gas is a full bar of that gas — true, but it
	 * reads as a measurement it isn't. Two species minimum.
	 */
	export function hasCompositionBar(composition: Composition | undefined): boolean {
		return (composition?.species.length ?? 0) > 1;
	}
</script>

<script lang="ts">
	/**
	 * The atmosphere composition bar and its unit caption. Drawn by the
	 * Overview's Atmosphere section and by the Structure tab, so the shares can
	 * never read differently across the two.
	 */
	import * as m from '$lib/paraglide/messages.js';
	import { speciesEntries } from '$lib/charts/atmosphere-species';
	import CompositionBar from './CompositionBar.svelte';

	interface Props {
		composition: Composition | undefined;
	}

	let { composition }: Props = $props();

	let entries = $derived(
		hasCompositionBar(composition) ? speciesEntries(composition!.species) : []
	);

	// Column and number densities are per-species measurements taken at
	// different times and geometries, not a mixing ratio. Too load-bearing to
	// hide behind a hover, so it rides under the legend as a caption.
	let compositionNote = $derived.by(() => {
		switch (composition?.unit) {
			case 'column_density':
			case 'number_density':
				return m.atmosphere_composition_relative_density();
			case 'mass_fraction':
				return m.atmosphere_composition_by_mass();
			default:
				return null;
		}
	});
</script>

<CompositionBar {entries} caption={compositionNote} />
