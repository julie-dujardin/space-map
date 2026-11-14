<!--
  What the site menu holds wherever it opens: the pages, then the links about
  the site, what is built on it and the settings, each behind one row so the
  trigger stays a single button. The phone sheet and the desktop map popover
  differ only in density and in whether the header rows carry a close button.
-->
<script lang="ts">
	import CheckIcon from '@lucide/svelte/icons/check';
	import ChevronLeftIcon from '@lucide/svelte/icons/chevron-left';
	import ChevronRightIcon from '@lucide/svelte/icons/chevron-right';
	import ExternalLinkIcon from '@lucide/svelte/icons/external-link';
	import SettingsIcon from '@lucide/svelte/icons/settings';
	import XIcon from '@lucide/svelte/icons/x';
	import type { Component } from 'svelte';
	import * as m from '$lib/paraglide/messages.js';
	import * as Sheet from '$lib/components/ui/sheet/index.js';
	import SettingsMenu, { type SettingsScope } from '../settings/SettingsMenu.svelte';
	import SiteMark from './SiteMark.svelte';
	import {
		ABOUT_LINKS,
		MORE_LINKS,
		SITE_COLUMN,
		SITE_GUTTER,
		SITE_PAGES,
		type NavPage,
		type SiteLink
	} from './site';

	interface Props {
		current?: NavPage;
		scope: SettingsScope;
		/** `sheet` is the phone's top sheet on the site column; `popover` the
		 *  desktop map's dropdown. */
		variant: 'sheet' | 'popover';
		/** Called when a page link is followed, so the host can close. */
		onNavigate?: () => void;
	}

	let { current, scope, variant, onNavigate }: Props = $props();

	type View = 'pages' | 'about' | 'more' | 'settings';
	let view = $state<View>('pages');

	const aboutActive = $derived(ABOUT_LINKS.some((link) => link.id === current));

	const sheet = $derived(variant === 'sheet');
	const column = $derived(sheet ? `${SITE_COLUMN} ${SITE_GUTTER}` : 'px-5');
	const row = $derived(
		`flex w-full items-center justify-between gap-3 transition-colors hover:text-foreground ${
			sheet ? `h-13 ${SITE_GUTTER} text-base` : 'h-10 px-5 text-sm'
		}`
	);
	const iconButton = `flex h-10 w-10 cursor-pointer items-center justify-center rounded-lg
		transition-colors hover:bg-accent hover:text-foreground`;
</script>

{#snippet pageLink(link: SiteLink)}
	{@const active = link.id === current}
	<li class="flex">
		<a
			href={link.href}
			aria-current={active ? 'page' : undefined}
			target={link.external ? '_blank' : undefined}
			rel={link.external ? 'noopener noreferrer' : undefined}
			class="{row} {active ? 'bg-accent font-medium text-foreground' : 'text-muted-foreground'}"
			onclick={onNavigate}
		>
			{link.label()}
			{#if active}
				<CheckIcon class="size-4.5" />
			{:else if link.external}
				<ExternalLinkIcon class="size-4.5" />
			{/if}
		</a>
	</li>
{/snippet}

{#snippet subview(
	target: View,
	label: string,
	Icon?: Component<{ class?: string }>,
	active = false
)}
	<button
		type="button"
		class="{row} cursor-pointer {active
			? 'bg-accent font-medium text-foreground'
			: 'text-muted-foreground'}"
		onclick={() => (view = target)}
	>
		<span class="flex items-center gap-3">
			{#if Icon}<Icon class="size-5" />{/if}
			{label}
		</span>
		<ChevronRightIcon class="size-4.5" />
	</button>
{/snippet}

<!-- Every view keeps it in the spot the first one shows it; the sub-views'
     headings top-align it, as the settings' two-line one is taller. -->
{#snippet closeButton(align = '')}
	{#if sheet}
		<Sheet.Close
			class="{iconButton} ms-auto shrink-0 {align} text-foreground"
			aria-label={m.close()}
		>
			<XIcon class="size-5" />
		</Sheet.Close>
	{/if}
{/snippet}

{#snippet subviewClose()}
	{@render closeButton('self-start')}
{/snippet}

{#snippet linkList(title: string, links: SiteLink[])}
	<!-- Lines the back button up with the settings' own, the close button with
	     the first view's. -->
	<header class="{sheet ? `${SITE_COLUMN} ps-4 pe-6` : 'px-3'} flex items-center gap-2 pt-2 pb-3">
		<button
			type="button"
			class="flex h-10 w-10 shrink-0 cursor-pointer items-center justify-center rounded-lg
				transition-colors hover:bg-accent"
			aria-label={m.back()}
			onclick={() => (view = 'pages')}
		>
			<ChevronLeftIcon class="size-5" />
		</button>
		<h2 class="text-base font-semibold">{title}</h2>
		{@render subviewClose()}
	</header>
	<nav aria-label={title} class="{sheet ? SITE_COLUMN : ''} pb-2">
		<ul class="flex flex-col">
			{#each links as link (link.id)}
				{@render pageLink(link)}
			{/each}
		</ul>
	</nav>
{/snippet}

{#if view === 'pages'}
	<div class="{column} flex shrink-0 items-center justify-between {sheet ? 'h-14' : 'h-12'}">
		<a
			href="/"
			class="flex items-center gap-2 text-foreground"
			aria-label={m.page_title()}
			onclick={onNavigate}
		>
			<SiteMark />
			<span class="text-[15px] font-semibold tracking-tight">{m.page_title()}</span>
		</a>
		{@render closeButton()}
	</div>

	<nav aria-label={m.nav_label()} class="{sheet ? SITE_COLUMN : ''} py-2">
		<ul class="flex flex-col">
			{#each SITE_PAGES as page (page.id)}
				{@render pageLink(page)}
			{/each}
		</ul>
	</nav>
	<div class={column}><div class="border-t border-border"></div></div>
	<div class="{sheet ? SITE_COLUMN : ''} py-2">
		{@render subview('about', m.nav_about(), undefined, aboutActive)}
		{@render subview('more', m.nav_more())}
	</div>
	<!-- The sheet's spare height goes above the settings, so they sit at the
	     bottom of the screen. -->
	<div class="{column} mt-auto"><div class="border-t border-border"></div></div>
	<div class="{sheet ? SITE_COLUMN : ''} py-2">
		{@render subview('settings', m.settings_title(), SettingsIcon)}
	</div>
{:else if view === 'about'}
	{@render linkList(m.nav_about(), ABOUT_LINKS)}
{:else if view === 'more'}
	{@render linkList(m.nav_more(), MORE_LINKS)}
{:else}
	<!-- px-1 lines the settings' own px-5 up with the site gutter. -->
	<div class="{sheet ? `${SITE_COLUMN} px-1` : ''} flex min-h-0 flex-1 flex-col">
		<SettingsMenu {scope} onBack={() => (view = 'pages')} headerEnd={subviewClose} />
	</div>
{/if}
