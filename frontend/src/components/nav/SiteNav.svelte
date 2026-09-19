<!--
  The row that carries the site between its non-map pages. The map names itself
  through its own chrome, so this is only for the document pages behind it.
  Phones get the pages and the settings behind one menu button instead of the
  tab strip.
-->
<script lang="ts">
	import SettingsIcon from '@lucide/svelte/icons/settings';
	import * as m from '$lib/paraglide/messages.js';
	import OverlayMenuButton from '../OverlayMenuButton.svelte';
	import SettingsMenu from '../settings/SettingsMenu.svelte';
	import SiteMark from './SiteMark.svelte';
	import SiteMenu from './SiteMenu.svelte';
	import { SITE_COLUMN, SITE_GUTTER, SITE_PAGES, type NavPage } from './site';
	import { ScrollArea } from '$lib/components/ui/scroll-area/index.js';
	import { cn } from '$lib/utils.js';

	interface Props {
		current?: NavPage;
		class?: string;
	}

	let { current, class: className }: Props = $props();
</script>

<header
	class={cn(
		'border-b border-border bg-background pt-[var(--safe-top)] ps-[var(--safe-start)] pe-[var(--safe-end)]',
		className
	)}
>
	<!-- -mb-px lifts the border under the active tab's own 2px underline. -->
	<nav
		aria-label={m.nav_label()}
		class="{SITE_COLUMN} {SITE_GUTTER} -mb-px flex h-14 items-stretch gap-4 md:gap-6"
	>
		<a
			href="/"
			class="flex shrink-0 items-center gap-2 text-foreground"
			aria-label={m.page_title()}
		>
			<SiteMark />
			<span class="text-[15px] font-semibold tracking-tight">{m.page_title()}</span>
		</a>

		<!-- Scrolls rather than wraps or truncates: the row grows by a page at a
		     time, and a wrapped second line would double the chrome. -->
		<ScrollArea
			orientation="horizontal"
			class="hidden min-w-0 flex-1 md:block"
			viewportClasses="[&>div]:h-full"
			scrollbarXClasses="h-1"
		>
			<ul class="flex h-full w-max min-w-full items-stretch gap-4 md:gap-6">
				{#each SITE_PAGES as page (page.id)}
					{@const active = page.id === current}
					<li class="flex shrink-0">
						<a
							href={page.href}
							aria-current={active ? 'page' : undefined}
							class="flex items-center whitespace-nowrap border-b-2 text-sm transition-colors {active
								? 'border-foreground font-medium text-foreground'
								: 'border-transparent text-muted-foreground hover:text-foreground'}"
						>
							{page.label()}
						</a>
					</li>
				{/each}
			</ul>
		</ScrollArea>

		<div class="hidden shrink-0 items-center md:flex">
			<OverlayMenuButton
				title={m.settings_title()}
				Icon={SettingsIcon}
				triggerClass="pointer-events-auto flex h-10 w-10 cursor-pointer items-center justify-center
					rounded-lg text-muted-foreground transition-colors hover:bg-accent
					hover:text-foreground md:h-8 md:w-8"
			>
				<SettingsMenu scope="page" />
			</OverlayMenuButton>
		</div>

		<div class="flex flex-1 items-center justify-end md:hidden">
			<SiteMenu {current} />
		</div>
	</nav>
</header>
