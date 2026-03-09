<script lang="ts">
	import { T } from '@threlte/core';
	import { HTML } from '@threlte/extras';
	import type { Satellite } from '$lib/types';

	interface Props {
		satellites: Satellite[];
		earthPosition: [number, number, number];
	}

	let { satellites, earthPosition }: Props = $props();
</script>

<!-- At solar system scale, satellites are invisible. Show a marker at Earth's position. -->
<T.Mesh position={earthPosition}>
	<T.RingGeometry args={[0.3, 0.35, 32]} />
	<T.MeshBasicMaterial color="#4da6ff" transparent opacity={0.5} side={2} />
	<HTML center pointerEvents="none" position.y={-0.5}>
		<span
			class="text-blue-300 text-xs whitespace-nowrap select-none"
			style="text-shadow: 0 0 4px black"
		>
			{satellites.length} satellites
		</span>
	</HTML>
</T.Mesh>
