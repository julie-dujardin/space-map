<script lang="ts">
	import ProbeTargets from '../sections/ProbeTargets.svelte';
	import type { TargetVisit } from '$lib/probes/target-list';

	interface Props {
		visits: TargetVisit[];
	}

	let { visits }: Props = $props();
</script>

<div class="flex flex-col gap-4">
	<ProbeTargets {visits} />
</div>
