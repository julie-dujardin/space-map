<!--
  The phone form of the site menu: one button opening a sheet under the row.
  The tab strip scrolled once the site had more pages than a phone row holds.
-->
<script lang="ts">
	import MenuIcon from '@lucide/svelte/icons/menu';
	import * as m from '$lib/paraglide/messages.js';
	import * as Sheet from '$lib/components/ui/sheet/index.js';
	import type { SettingsScope } from '../settings/SettingsMenu.svelte';
	import SiteMenuPanel from './SiteMenuPanel.svelte';
	import type { NavPage } from './site';

	interface Props {
		current?: NavPage;
		scope?: SettingsScope;
		/** The trigger's size and colour; the site row's default fits its 56px
		 *  height, the map's search pill passes a smaller one. */
		class?: string;
	}

	let {
		current,
		scope = 'page',
		class: className = 'h-10 w-10 text-muted-foreground'
	}: Props = $props();

	let open = $state(false);
</script>

<Sheet.Root bind:open>
	<Sheet.Trigger
		class="flex cursor-pointer items-center justify-center rounded-lg transition-colors hover:bg-accent hover:text-foreground {className}"
		aria-label={m.nav_menu()}
	>
		<MenuIcon class="size-5" />
	</Sheet.Trigger>
	<!-- The sheet repeats the site row so the mark and the close button sit
	     where the mark and the menu button were. -->
	<Sheet.Content
		side="top"
		showCloseButton={false}
		class="max-h-dvh gap-0 overflow-y-auto pt-[var(--safe-top)] ps-[var(--safe-start)] pe-[var(--safe-end)]"
	>
		<Sheet.Title class="sr-only">{m.nav_menu()}</Sheet.Title>
		<SiteMenuPanel {current} {scope} variant="sheet" onNavigate={() => (open = false)} />
	</Sheet.Content>
</Sheet.Root>
