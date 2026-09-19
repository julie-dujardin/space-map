<!--
  The phone form of the site row: one button opening a sheet under the row
  with the pages and the settings. The tab strip scrolled once the site had
  more pages than a phone row holds.
-->
<script lang="ts">
	import CheckIcon from '@lucide/svelte/icons/check';
	import ChevronRightIcon from '@lucide/svelte/icons/chevron-right';
	import MenuIcon from '@lucide/svelte/icons/menu';
	import SettingsIcon from '@lucide/svelte/icons/settings';
	import XIcon from '@lucide/svelte/icons/x';
	import * as m from '$lib/paraglide/messages.js';
	import * as Sheet from '$lib/components/ui/sheet/index.js';
	import SettingsMenu from '../settings/SettingsMenu.svelte';
	import SiteMark from './SiteMark.svelte';
	import { SITE_COLUMN, SITE_GUTTER, SITE_PAGES, type NavPage } from './site';

	interface Props {
		current: NavPage;
		class?: string;
	}

	let { current, class: className }: Props = $props();

	let open = $state(false);
	// Settings open inside the same sheet, so the row keeps a single button.
	let view = $state<'pages' | 'settings'>('pages');

	const iconButton = `flex h-10 w-10 cursor-pointer items-center justify-center rounded-lg
		transition-colors hover:bg-accent hover:text-foreground`;
	const row = `flex h-13 w-full items-center justify-between gap-3 ${SITE_GUTTER} text-base
		transition-colors hover:text-foreground`;
</script>

<Sheet.Root
	bind:open
	onOpenChange={(shown) => {
		if (!shown) view = 'pages';
	}}
>
	<Sheet.Trigger class="{iconButton} text-muted-foreground {className}" aria-label={m.nav_menu()}>
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
		<div class="{SITE_COLUMN} {SITE_GUTTER} flex h-14 shrink-0 items-center justify-between">
			<a
				href="/"
				class="flex items-center gap-2 text-foreground"
				aria-label={m.page_title()}
				onclick={() => (open = false)}
			>
				<SiteMark />
				<span class="text-[15px] font-semibold tracking-tight">{m.page_title()}</span>
			</a>
			<Sheet.Close class="{iconButton} text-foreground" aria-label={m.close()}>
				<XIcon class="size-5" />
			</Sheet.Close>
		</div>

		{#if view === 'pages'}
			<nav aria-label={m.nav_label()} class="{SITE_COLUMN} py-2">
				<ul class="flex flex-col">
					{#each SITE_PAGES as page (page.id)}
						{@const active = page.id === current}
						<li class="flex">
							<a
								href={page.href}
								aria-current={active ? 'page' : undefined}
								class="{row} {active
									? 'bg-accent font-medium text-foreground'
									: 'text-muted-foreground'}"
								onclick={() => (open = false)}
							>
								{page.label()}
								{#if active}
									<CheckIcon class="size-4.5" />
								{/if}
							</a>
						</li>
					{/each}
				</ul>
			</nav>
			<div class="{SITE_COLUMN} {SITE_GUTTER}"><div class="border-t border-border"></div></div>
			<div class="{SITE_COLUMN} py-2">
				<button
					type="button"
					class="{row} cursor-pointer text-muted-foreground"
					onclick={() => (view = 'settings')}
				>
					<span class="flex items-center gap-3">
						<SettingsIcon class="size-5" />
						{m.settings_title()}
					</span>
					<ChevronRightIcon class="size-4.5" />
				</button>
			</div>
		{:else}
			<!-- px-1 lines the settings' own px-5 up with the site gutter. -->
			<div class="{SITE_COLUMN} px-1">
				<SettingsMenu scope="page" onBack={() => (view = 'pages')} />
			</div>
		{/if}
	</Sheet.Content>
</Sheet.Root>
