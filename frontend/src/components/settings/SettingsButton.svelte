<script lang="ts">
	import SettingsIcon from '@lucide/svelte/icons/settings';
	import * as m from '$lib/paraglide/messages.js';
	import OverlayMenuButton from '../OverlayMenuButton.svelte';
	import SettingsMenu, { type SettingsScope } from './SettingsMenu.svelte';

	interface Props {
		scope?: SettingsScope;
	}

	let { scope = 'map' }: Props = $props();
</script>

<OverlayMenuButton title={m.settings_title()} Icon={SettingsIcon}>
	<SettingsMenu {scope} />
</OverlayMenuButton>
