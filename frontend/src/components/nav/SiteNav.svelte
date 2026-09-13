<!--
  The row that carries the site between its non-map pages. The map names itself
  through its own chrome, so this is only for the document pages behind it.

  Its own max-width rather than the page's: the pages differ (prose at 2xl,
  the gallery at 4xl) and chrome that shifts on navigation reads as a reload.
-->
<script lang="ts">
	import SettingsIcon from '@lucide/svelte/icons/settings';
	import * as m from '$lib/paraglide/messages.js';
	import OverlayMenuButton from '../OverlayMenuButton.svelte';
	import SettingsMenu from '../settings/SettingsMenu.svelte';
	import SiteMark from './SiteMark.svelte';

	/** A page this row links to; `current` names the one being rendered. */
	export type NavPage = 'map' | 'panoramas' | 'credits';

	interface Props {
		current: NavPage;
	}

	let { current }: Props = $props();

	const pages: { id: NavPage; href: string; label: () => string }[] = [
		{ id: 'map', href: '/', label: m.nav_map },
		{ id: 'panoramas', href: '/view', label: m.nav_panoramas },
		{ id: 'credits', href: '/credits', label: m.credits_page_title }
	];
</script>

<header
	class="shrink-0 border-b border-border bg-background pt-[var(--safe-top)] ps-[var(--safe-start)] pe-[var(--safe-end)]"
>
	<!-- -mb-px lifts the border under the active tab's own 2px underline. -->
	<nav
		aria-label={m.nav_label()}
		class="mx-auto -mb-px flex h-14 max-w-4xl items-stretch gap-4 px-6 md:gap-6"
	>
		<a
			href="/"
			class="flex shrink-0 items-center gap-2 text-foreground"
			aria-label={m.page_title()}
		>
			<SiteMark />
			<!-- Off the narrowest phones the mark carries it: several locales
			     translate the name, and the long ones crowd out the tabs. -->
			<span class="hidden text-[15px] font-semibold tracking-tight sm:inline">
				{m.page_title()}
			</span>
		</a>

		<!-- Scrolls rather than wraps or truncates: the row grows by a page at a
		     time, and a wrapped second line would double the chrome. -->
		<ul class="no-scrollbar flex min-w-0 flex-1 items-stretch gap-4 overflow-x-auto md:gap-6">
			{#each pages as page (page.id)}
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

		<div class="flex shrink-0 items-center">
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
	</nav>
</header>
