<!--
  The glass menu button the full-screen views carry in their top-right corner,
  where the settings gear was: it opens the site menu with the settings behind
  it, so a view that has no site row still reaches every page.
-->
<script lang="ts">
	import MenuIcon from '@lucide/svelte/icons/menu';
	import * as m from '$lib/paraglide/messages.js';
	import OverlayMenuButton from '../OverlayMenuButton.svelte';
	import SiteMenuPanel from './SiteMenuPanel.svelte';
	import type { SettingsScope } from '../settings/SettingsMenu.svelte';
	import type { NavPage } from './site';

	interface Props {
		current?: NavPage;
		scope?: SettingsScope;
	}

	let { current = 'map', scope = 'map' }: Props = $props();
</script>

<OverlayMenuButton title={m.nav_menu()} Icon={MenuIcon}>
	<SiteMenuPanel {current} {scope} variant="popover" />
</OverlayMenuButton>
