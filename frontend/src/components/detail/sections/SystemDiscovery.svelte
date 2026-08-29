<script lang="ts">
	// When this system's moons were found — the Moons collection's timeline asked
	// of one system. Same chart and same heading pattern the collection pages use.
	import YearHistogramChart from '../charts/YearHistogramChart.svelte';
	import * as m from '$lib/paraglide/messages.js';

	interface Props {
		histogram: Record<string, number>;
	}
	let { histogram }: Props = $props();
</script>

<div class="flex flex-col gap-1">
	<h3 class="text-sm font-medium">{m.system_moon_discovery()}</h3>
	<div class="border-border/60 border-t"></div>
	<div class="pt-1">
		<YearHistogramChart {histogram} kind="discovery" />
	</div>
</div>
