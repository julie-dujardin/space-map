<!--
  The map's menu button: the glass button in the top-right corner where the
  settings gear was, opening the site menu with the settings behind it.
-->
<script lang="ts">
	import MenuIcon from '@lucide/svelte/icons/menu';
	import * as m from '$lib/paraglide/messages.js';
	import OverlayMenuButton from '../OverlayMenuButton.svelte';
	import SiteMenuPanel from './SiteMenuPanel.svelte';
</script>

<OverlayMenuButton title={m.nav_menu()} Icon={MenuIcon}>
	<SiteMenuPanel current="map" scope="map" variant="popover" />
</OverlayMenuButton>
