<script lang="ts" module>
	import type { GlobalObjectData } from '$lib/fetch/objects/object-data';

	/** For a host section that would otherwise not render at all. */
	export function hasMassDensity(global: GlobalObjectData | null): boolean {
		return !!(global?.sbdb?.mass || global?.wikidata?.mass || global?.wikidata?.density);
	}
</script>

<script lang="ts">
	/** The whole-body rows the interior is modelled over — shared between the
	 *  Overview's Interior section and the Structure tab's. */
	import * as m from '$lib/paraglide/messages.js';
	import { formatDensity } from '$lib/format/quantities';
	import { massReading } from '$lib/format/mass';
	import Row from './Row.svelte';

	interface Props {
		global: GlobalObjectData | null;
	}

	let { global }: Props = $props();

	let mass = $derived(global?.sbdb?.mass ?? global?.wikidata?.mass);
	let reading = $derived(mass && massReading(mass));
	let density = $derived(global?.wikidata?.density);
</script>

{#if reading}
	<Row label={m.property_name_mass()} value={reading.value} valueTooltip={reading.tooltip} />
{/if}
{#if density}
	<Row label={m.property_name_density()} value={formatDensity(density)} />
{/if}
