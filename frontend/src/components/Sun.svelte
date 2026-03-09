<script lang="ts">
	import { T } from '@threlte/core';
</script>

<T.PointLight intensity={2} position={[0, 0, 0]} />

<T.Mesh>
	<T.SphereGeometry args={[0.5, 32, 32]} />
	<T.MeshBasicMaterial color="#ffdd44" />
</T.Mesh>
