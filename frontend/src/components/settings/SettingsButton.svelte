<script lang="ts">
	import SettingsIcon from '@lucide/svelte/icons/settings';
	import * as m from '$lib/paraglide/messages.js';
	import OverlayMenuButton from '../OverlayMenuButton.svelte';
	import SettingsMenu from './SettingsMenu.svelte';
</script>

<OverlayMenuButton title={m.settings_title()} Icon={SettingsIcon}>
	<SettingsMenu />
</OverlayMenuButton>
