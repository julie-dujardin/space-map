<!--
  The phone form of the site menu: one button opening a fullscreen sheet, like
  the settings behind it, so the page never shows through under either.
-->
<script lang="ts">
	import MenuIcon from '@lucide/svelte/icons/menu';
	import { getContext, hasContext } from 'svelte';
	import type { MapCover } from '$lib/state/map-cover.svelte';
	import * as m from '$lib/paraglide/messages.js';
	import * as Sheet from '$lib/components/ui/sheet/index.js';
	import { ScrollArea } from '$lib/components/ui/scroll-area/index.js';
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

	// The sheet covers the whole map, so the map can pause behind it.
	const mapCover = hasContext('mapCover') ? getContext<MapCover>('mapCover') : null;
	mapCover?.hold(() => open);
</script>

<Sheet.Root bind:open>
	<Sheet.Trigger
		class="flex cursor-pointer items-center justify-center rounded-lg transition-colors hover:bg-accent hover:text-foreground {className}"
		aria-label={m.nav_menu()}
	>
		<MenuIcon class="size-5" />
	</Sheet.Trigger>
	<!-- The sheet repeats the site row so the mark and the close button sit
	     where the mark and the menu button were. It stacks above the detail
	     drawers, on the tier the map's menu dialog uses. -->
	<Sheet.Content
		side="top"
		showCloseButton={false}
		overlayClass="z-[69]"
		class="z-[70] gap-0 overflow-hidden pt-[var(--safe-top)] pb-[var(--safe-bottom)] ps-[var(--safe-start)] pe-[var(--safe-end)] data-[side=top]:h-dvh data-[side=top]:border-b-0"
	>
		<Sheet.Title class="sr-only">{m.nav_menu()}</Sheet.Title>
		<ScrollArea
			class="flex min-h-0 flex-1 flex-col"
			viewportClasses="min-h-0 flex-1 [&>div]:flex [&>div]:min-h-full [&>div]:flex-col"
		>
			<SiteMenuPanel {current} {scope} variant="sheet" onNavigate={() => (open = false)} />
		</ScrollArea>
	</Sheet.Content>
</Sheet.Root>
