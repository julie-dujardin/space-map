<!-- The sky culture of the constellation layer, as a page inside Layers. -->
<script lang="ts">
	import { getContext } from 'svelte';
	import CheckIcon from '@lucide/svelte/icons/check';
	import { ScrollArea } from '$lib/components/ui/scroll-area/index.js';
	import { isCoarsePointer } from '$lib/device';
	import { cultureName, type SkyCultureEntry } from '$lib/fetch/extrasolar/skycultures';
	import { formatNumber } from '$lib/format/quantities';
	import { SKY_CULTURE_SLUG_PREFIX } from '$lib/fetch/groups/registry';
	import { isModifiedClick } from '$lib/modified-click';
	import { getLocale } from '$lib/paraglide/runtime.js';
	import type { AppState } from '$lib/state/app-state.svelte';
	import { groupHref } from '$lib/state/focus-link';
	import * as m from '$lib/paraglide/messages.js';
	import InlineMenu from '../detail/travel/InlineMenu.svelte';
	import SearchBox from '../detail/travel/SearchBox.svelte';
	import BackPill from '../search/BackPill.svelte';
	import {
		byRegion,
		matchCulture,
		orderCultures,
		regionLabel,
		type SkyCultureOrder
	} from './sky-culture-list';

	interface Props {
		cultures: readonly SkyCultureEntry[];
		/** Key of the culture on show. */
		picked: string | undefined;
		onPick: (culture: SkyCultureEntry) => void;
		onBack: () => void;
	}
	let { cultures, picked, onPick, onBack }: Props = $props();

	const appState = getContext<AppState>('appState');

	const locale = getLocale();
	const orders: { value: SkyCultureOrder; label: string }[] = [
		{ value: 'region', label: m.layers_sky_culture_by_region() },
		{ value: 'name', label: m.layers_sky_culture_by_name() },
		{ value: 'figures', label: m.layers_sky_culture_by_figures() }
	];

	let query = $state('');
	let order = $state<SkyCultureOrder>('region');
	let input = $state<HTMLInputElement | null>(null);

	const searching = $derived(query.trim().length > 0);
	const hits = $derived(
		orderCultures(
			cultures.filter((culture) => matchCulture(culture, query.trim(), locale)),
			'name',
			locale
		)
	);

	// Autofocus is a desktop gesture: on touch it throws the keyboard over the list.
	$effect(() => {
		if (!isCoarsePointer()) input?.focus();
	});
</script>

{#snippet row(culture: SkyCultureEntry, region?: string)}
	{@const selected = culture.key === picked}
	{@const name = cultureName(culture, locale)}
	<a
		href={groupHref(appState, `${SKY_CULTURE_SLUG_PREFIX}${culture.key}`, name)}
		aria-current={selected ? 'true' : undefined}
		onclick={(e) => {
			if (isModifiedClick(e)) return;
			e.preventDefault();
			onPick(culture);
		}}
		class="hover:bg-muted flex min-h-11 min-w-0 items-center gap-2 rounded-md px-2 py-1.5 text-start text-sm transition-colors md:min-h-0 {selected
			? 'bg-muted'
			: ''}"
	>
		<span class="min-w-0 flex-1">
			<span class="block truncate"><bdi>{name}</bdi></span>
			{#if region}
				<span class="text-muted-foreground block truncate text-[11px] leading-[14px]">{region}</span
				>
			{/if}
		</span>
		<span class="text-muted-foreground shrink-0 font-mono text-[11px] tabular-nums"
			>{formatNumber(culture.figures)}</span
		>
		{#if selected}<CheckIcon class="size-3.5 shrink-0" aria-hidden="true" />{/if}
	</a>
{/snippet}

<div class="flex h-[640px] max-h-full min-h-0 flex-1 flex-col">
	<div
		class="flex h-[60px] shrink-0 items-center px-3 md:h-[42px] md:border-b md:border-border md:px-2"
	>
		<BackPill label={m.layers_sky_culture()} onclick={onBack} />
	</div>
	<div class="flex min-h-0 flex-1 flex-col gap-2 p-3 pt-0 md:p-2">
		<div class="flex shrink-0 items-center gap-2">
			<SearchBox
				bind:input
				bind:value={query}
				label={m.layers_sky_culture_search()}
				class="min-w-0 flex-1"
				dir="auto"
			/>
			{#if !searching}
				<InlineMenu
					options={orders}
					value={order}
					onchange={(value) => (order = value)}
					ariaLabel={m.layers_sky_culture_order()}
					align="end"
					muted
				/>
			{/if}
		</div>
		<ScrollArea
			class="flex min-h-0 flex-1 flex-col"
			viewportClasses="min-h-0 flex-1 [&>div]:pe-2.5"
		>
			{#if searching}
				{#each hits as culture (culture.key)}
					{@render row(culture, regionLabel(culture.group))}
				{:else}
					<p class="text-muted-foreground px-2 text-xs">{m.travel_search_empty()}</p>
				{/each}
			{:else}
				<p class="text-muted-foreground px-2 pb-1 text-xs">{m.layers_sky_culture_intro()}</p>
				{#if order === 'region'}
					{#each byRegion(cultures, locale) as region (region.group)}
						<div
							class="bg-popover max-md:bg-background sticky top-0 z-[1] flex justify-between gap-2 px-2 pt-2 pb-1 text-[10px] font-semibold tracking-[0.12em] text-muted-foreground uppercase rtl:text-xs rtl:tracking-normal"
						>
							<span>{region.label}</span>
							<span class="font-mono font-normal tracking-normal tabular-nums"
								>{formatNumber(region.cultures.length)}</span
							>
						</div>
						{#each region.cultures as culture (culture.key)}
							{@render row(culture)}
						{/each}
					{/each}
				{:else}
					{#each orderCultures(cultures, order, locale) as culture (culture.key)}
						{@render row(culture)}
					{/each}
				{/if}
			{/if}
		</ScrollArea>
	</div>
</div>
