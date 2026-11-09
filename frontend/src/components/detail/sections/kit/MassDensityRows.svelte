<script lang="ts" module>
	import type { GlobalObjectData } from '$lib/fetch/objects/object-data';

	/** For a host section that would otherwise not render at all. */
	export function hasMassDensity(global: GlobalObjectData | null): boolean {
		return global?.mass_kg != null || global?.mean_density_g_cm3 != null;
	}
</script>

<script lang="ts">
	/** The whole-body rows the interior is modelled over — shared between the
	 *  Overview's Interior section and the Structure tab's. */
	import { densityRow, massRow } from './body-rows';
	import Row from './Row.svelte';

	interface Props {
		global: GlobalObjectData | null;
	}

	let { global }: Props = $props();

	let rows = $derived([massRow(global), densityRow(global)].filter((row) => row !== null));
</script>

{#each rows as row (row.label)}
	<Row
		label={row.label}
		tooltip={row.tooltip}
		value={row.value}
		valueTooltip={row.valueTooltip}
		note={row.note}
	/>
{/each}
