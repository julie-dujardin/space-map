<!--
  What the site menu holds wherever it opens: the pages, then the settings
  behind one row so the trigger stays a single button. The phone sheet and the
  desktop map popover differ only in density and in whether the header row
  carries a close button.
-->
<script lang="ts">
	import CheckIcon from '@lucide/svelte/icons/check';
	import ChevronRightIcon from '@lucide/svelte/icons/chevron-right';
	import SettingsIcon from '@lucide/svelte/icons/settings';
	import XIcon from '@lucide/svelte/icons/x';
	import * as m from '$lib/paraglide/messages.js';
	import * as Sheet from '$lib/components/ui/sheet/index.js';
	import SettingsMenu, { type SettingsScope } from '../settings/SettingsMenu.svelte';
	import SiteMark from './SiteMark.svelte';
	import { SITE_COLUMN, SITE_GUTTER, SITE_PAGES, type NavPage } from './site';

	interface Props {
		current?: NavPage;
		scope: SettingsScope;
		/** `sheet` is the phone's top sheet on the site column; `popover` the
		 *  desktop map's dropdown. */
		variant: 'sheet' | 'popover';
		/** Called when a page link is followed, so the host can close. */
		onNavigate?: () => void;
		/** Bound by the host so it can size itself to the view. */
		view?: 'pages' | 'settings';
	}

	let { current, scope, variant, onNavigate, view = $bindable('pages') }: Props = $props();

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
		{#if sheet}
			<Sheet.Close class="{iconButton} text-foreground" aria-label={m.close()}>
				<XIcon class="size-5" />
			</Sheet.Close>
		{/if}
	</div>

	<nav aria-label={m.nav_label()} class="{sheet ? SITE_COLUMN : ''} py-2">
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
						onclick={onNavigate}
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
	<div class={column}><div class="border-t border-border"></div></div>
	<div class="{sheet ? SITE_COLUMN : ''} py-2">
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
	<div class="{sheet ? `${SITE_COLUMN} px-1` : ''} flex min-h-0 flex-col">
		<SettingsMenu {scope} onBack={() => (view = 'pages')} />
	</div>
{/if}
