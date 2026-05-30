<script lang="ts">
	import LayersIcon from '@lucide/svelte/icons/layers';
	import * as m from '$lib/paraglide/messages.js';
	import OverlayMenuButton from '../OverlayMenuButton.svelte';
	import LayersMenu from './LayersMenu.svelte';
</script>

<OverlayMenuButton title={m.layers_title()} Icon={LayersIcon}>
	<LayersMenu />
</OverlayMenuButton>
