<script lang="ts">
	import PanoramaViewer from '../../../../components/panorama/PanoramaViewer.svelte';

	let { data } = $props();
</script>

<PanoramaViewer bodyId={data.bodyId} />
