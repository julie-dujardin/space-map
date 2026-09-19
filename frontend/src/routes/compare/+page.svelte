<!--
  Size comparison, full page: the row is the screen, and everything else floats
  over it. The list at the side is what is being compared; how that set is
  broken into pages is decided here, when it is drawn, from the sizes alone.
-->
<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import ChevronLeftIcon from '@lucide/svelte/icons/chevron-left';
	import ChevronRightIcon from '@lucide/svelte/icons/chevron-right';
	import ChevronsLeftIcon from '@lucide/svelte/icons/chevrons-left';
	import ExternalLinkIcon from '@lucide/svelte/icons/external-link';
	import ListIcon from '@lucide/svelte/icons/list';
	import MenuIcon from '@lucide/svelte/icons/menu';
	import PlusIcon from '@lucide/svelte/icons/plus';
	import XIcon from '@lucide/svelte/icons/x';
	import * as m from '$lib/paraglide/messages.js';
	import * as Popover from '$lib/components/ui/popover';
	import { ScrollArea } from '$lib/components/ui/scroll-area/index.js';
	import SiteNav from '../../components/nav/SiteNav.svelte';
	import ComparePicker from '../../components/compare/ComparePicker.svelte';
	import BodyLineup, { type LineupBody } from '../../components/detail/charts/BodyLineup.svelte';
	import { bandsBySize } from '$lib/compare/pages';
	import { lineupBody, resolveObject, type CompareObject } from '$lib/compare/geometry';
	import { COMPARE_PRESETS, presetOn, type ComparePreset } from '$lib/compare/presets';
	import type { ObjectHit } from '$lib/search/client';
	import { formatQuantity } from '$lib/format/quantities';
	import { BODY_COLORS, DEFAULT_BODY_COLOR } from '$lib/constants';
	import { bodyHref } from '$lib/state/url';

	let { data } = $props();

	/** Below this the rail has no room to stand beside the row. */
	const NARROW = 768;
	/** How far a finger travels before it counts as a page turn. */
	const SWIPE_PX = 60;
	/** The band of names the row draws under itself. */
	const LABEL_ROW = 48;

	let innerWidth = $state(NARROW + 1);
	const narrow = $derived(innerWidth <= NARROW);

	let railOpen = $state(true);
	let pickerOpen = $state(false);
	let stageHeight = $state(0);
	let page = $state(0);
	let menu = $state<{ id: string; x: number; y: number } | null>(null);
	/** The strip and the pill on one side are one control: both light together. */
	let hot = $state<'prev' | 'next' | null>(null);
	let laid = $state<
		{ id: string; cx: number; cy: number; pr: number; radiusKm: number; aside?: 'start' | 'end' }[]
	>([]);

	const selected = $derived(data.selected);

	/** Everything resolved so far, by id. An object is drawn as soon as its own
	 *  bundle answers; the ones still in flight simply aren't in the row yet. */
	let resolved = $state<Record<string, CompareObject>>({});
	/** Names from the search hit that added an object, so a row can be labelled
	 *  before its bundle lands. */
	const seeds = new Map<string, { name: string; type?: string; diameter_km?: number }>();
	const asked = new Set<string>();

	$effect(() => {
		for (const id of selected) {
			if (asked.has(id)) continue;
			asked.add(id);
			resolveObject(id, seeds.get(id) ?? { name: '' })
				.then((object) => {
					if (object) resolved[object.id] = object;
				})
				.catch(() => asked.delete(id));
		}
	});

	const objects = $derived(
		selected.map((id) => resolved[id]).filter((o): o is CompareObject => !!o)
	);
	const bands = $derived(bandsBySize(objects, (o) => o.radiusKm));
	const pageIndex = $derived(Math.min(page, Math.max(0, bands.length - 1)));
	const band = $derived(bands[pageIndex]);
	const bodies = $derived<LineupBody[]>(
		band
			? [
					...band.items.map(lineupBody),
					...(band.previous ? [{ ...lineupBody(band.previous), aside: 'start' as const }] : []),
					...(band.next ? [{ ...lineupBody(band.next), aside: 'end' as const }] : [])
				]
			: []
	);

	/** Sorted for the side list: the row's own order, largest first. */
	const listed = $derived([...objects].sort((a, b) => b.radiusKm - a.radiusKm));

	// A shorter set can strand the reader on a page that no longer exists.
	$effect(() => {
		if (page > bands.length - 1) page = Math.max(0, bands.length - 1);
	});

	/** Pixels per kilometre on this page, read off whatever the row laid out. */
	const pxPerKm = $derived.by(() => {
		const first = laid.find((l) => !l.aside);
		return first ? first.pr / first.radiusKm : 0;
	});

	/** Where the row put the pages on either side of this one: what it drew of
	 *  them is also the way to them. */
	const ghostAt = $derived(laid.find((l) => l.aside === 'start'));
	const speckAt = $derived(laid.find((l) => l.aside === 'end'));

	function colorOf(object: CompareObject): string {
		return object.geometry.color ?? BODY_COLORS[object.id] ?? DEFAULT_BODY_COLOR;
	}

	function sizeText(object: CompareObject): string {
		const span = object.radiusKm * 2 * (object.geometry.meshSpanRatio ?? 1);
		return object.geometry.craft
			? formatQuantity({ value: span * 1000, unit: 'metre' }, true)
			: formatQuantity({ value: span, unit: 'kilometre' }, true);
	}

	// --- the set itself, which lives in the query string ---

	function setIds(ids: readonly string[]): void {
		goto(`${resolve('/compare')}?m=${ids.join(',')}`, {
			replaceState: true,
			noScroll: true,
			keepFocus: true
		});
	}

	function addHit(hit: ObjectHit): void {
		seeds.set(hit.id, { name: hit.name, type: hit.type, diameter_km: hit.diameter_km });
		setIds([...selected, hit.id]);
		pickerOpen = false;
	}

	/** A preset is on when everything in it is up, however it got there. Turning
	 *  it on adds what is missing; turning it off takes its members away and
	 *  leaves the rest of the comparison standing. */
	function togglePreset(preset: ComparePreset): void {
		page = 0;
		setIds(
			presetOn(preset, selected)
				? selected.filter((id) => !preset.ids.includes(id))
				: [...selected, ...preset.ids.filter((id) => !selected.includes(id))]
		);
		pickerOpen = false;
	}

	function remove(id: string): void {
		menu = null;
		setIds(selected.filter((other) => other !== id));
	}

	// --- pages, which are only a way of drawing the set ---

	function turn(delta: number): void {
		page = Math.min(Math.max(pageIndex + delta, 0), Math.max(0, bands.length - 1));
		menu = null;
	}

	let swipeFrom: number | null = null;
	function onSwipeStart(event: PointerEvent): void {
		swipeFrom = event.pointerType === 'touch' ? event.clientX : null;
	}
	function onSwipeEnd(event: PointerEvent): void {
		if (swipeFrom === null) return;
		const dx = event.clientX - swipeFrom;
		swipeFrom = null;
		if (Math.abs(dx) >= SWIPE_PX) turn(dx < 0 ? 1 : -1);
	}

	/** A round distance about 110 px long, for the bar the row is measured by. */
	const scaleBar = $derived.by(() => {
		if (!pxPerKm) return null;
		const raw = 110 / pxPerKm;
		const exponent = Math.floor(Math.log10(raw));
		const lead = raw / 10 ** exponent;
		const km = (lead >= 5 ? 5 : lead >= 2 ? 2 : 1) * 10 ** exponent;
		const label =
			km < 1
				? formatQuantity({ value: km * 1000, unit: 'metre' }, true)
				: formatQuantity({ value: km, unit: 'kilometre' }, true);
		return { px: km * pxPerKm, label };
	});

	// The row draws both neighbouring bands itself, at its own scale — the page
	// only names them.
	const ghost = $derived(band?.previous);
	const speck = $derived(band?.next);

	const menuObject = $derived(menu ? resolved[menu.id] : undefined);
</script>

<svelte:head>
	<title>{m.compare_page_title()} - {m.page_title()}</title>
</svelte:head>

<svelte:window
	bind:innerWidth
	onkeydown={(e) => {
		if (e.key === 'Escape') menu = null;
	}}
/>

<div class="flex h-dvh flex-col overflow-hidden bg-background">
	<SiteNav current="compare" class="shrink-0" />

	<div class="relative flex min-h-0 flex-1">
		{#if railOpen && !narrow}
			<!-- The comparison: one row per object, largest first, as drawn. -->
			<aside class="flex w-[300px] shrink-0 flex-col border-e border-border bg-card">
				<ScrollArea class="min-h-0 flex-1">
					<div class="flex flex-col gap-4 p-5">
						<div class="flex items-center gap-2">
							<h1 class="flex-1 text-[17px] font-semibold tracking-tight">
								{m.compare_page_title()}
							</h1>
							<span class="text-xs text-muted-foreground"
								>{m.compare_object_count({ count: objects.length })}</span
							>
							<button
								type="button"
								aria-label={m.compare_hide_list()}
								aria-expanded="true"
								onclick={() => (railOpen = false)}
								class="flex size-7 items-center justify-center rounded-lg text-muted-foreground hover:bg-accent hover:text-foreground"
							>
								<ChevronsLeftIcon class="size-4" />
							</button>
						</div>

						<div class="flex flex-col gap-2">
							<span class="text-[11px] font-medium tracking-wider text-muted-foreground uppercase"
								>{m.compare_presets()}</span
							>
							<div class="flex flex-wrap gap-1.5">
								{#each COMPARE_PRESETS as preset (preset.slug)}
									{@const on = presetOn(preset, selected)}
									<button
										type="button"
										aria-pressed={on}
										onclick={() => togglePreset(preset)}
										class="h-7 rounded-lg border px-2.5 text-xs transition-colors {on
											? 'border-primary bg-primary/10 font-medium text-foreground'
											: 'border-border hover:bg-accent'}"
									>
										{preset.label()}
									</button>
								{/each}
							</div>
						</div>

						<Popover.Root bind:open={pickerOpen}>
							<Popover.Trigger
								class="flex h-11 items-center justify-center gap-2 rounded-xl border border-dashed border-border bg-accent/40 text-sm font-medium hover:bg-accent"
							>
								<PlusIcon class="size-4" />
								{m.compare_add()}
							</Popover.Trigger>
							<Popover.Content side="right" align="start" sideOffset={10} class="w-[380px] p-0">
								<ComparePicker chosen={selected} onadd={addHit} onpreset={togglePreset} />
							</Popover.Content>
						</Popover.Root>

						<ul class="flex flex-col border-t border-border">
							{#each listed as object (object.id)}
								<li class="flex h-11 items-center gap-2.5 border-b border-border/60">
									<span class="size-2.5 shrink-0 rounded-full" style="background: {colorOf(object)}"
									></span>
									<a
										href={bodyHref(object.id, object.name)}
										class="flex-1 truncate text-[13.5px] font-medium hover:underline"
										>{object.name}</a
									>
									<span class="shrink-0 text-xs text-muted-foreground tabular-nums"
										>{sizeText(object)}</span
									>
									<button
										type="button"
										aria-label={m.compare_remove({ name: object.name })}
										onclick={() => remove(object.id)}
										class="flex size-6 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
									>
										<XIcon class="size-3.5" />
									</button>
								</li>
							{/each}
						</ul>

						{#if objects.length}
							<div class="flex gap-4">
								<button
									type="button"
									onclick={() => setIds([])}
									class="text-xs text-muted-foreground hover:text-foreground"
									>{m.compare_clear()}</button
								>
							</div>
						{/if}
					</div>
				</ScrollArea>
			</aside>
		{/if}

		<!-- The row. Always dark: it is the same sky the map draws. -->
		<div
			bind:clientHeight={stageHeight}
			role="group"
			aria-label={m.compare_lineup_label()}
			class="relative min-w-0 flex-1 overflow-hidden bg-[#0b0b0c] text-white"
			style="--muted-foreground: oklch(0.72 0 0)"
			onpointerdown={onSwipeStart}
			onpointerup={onSwipeEnd}
			onpointercancel={() => (swipeFrom = null)}
		>
			{#if bodies.length && stageHeight > LABEL_ROW}
				<!-- The row draws the neighbouring pages too, at its own scale. -->
				<div class="relative">
					<BodyLineup
						{bodies}
						ariaLabel={m.compare_lineup_label()}
						height={stageHeight - LABEL_ROW}
						boxed
						labels
						ground="transparent"
						spread={false}
						onlayout={(items) => (laid = items)}
						oncontextpick={(id, x, y) => (menu = { id, x, y })}
					/>
				</div>
			{:else}
				<p class="flex h-full items-center justify-center text-sm text-white/60">
					{objects.length === 0 && selected.length > 0 ? m.compare_loading() : m.compare_empty()}
				</p>
			{/if}

			{#if ghost}
				<!-- The strip of the page before is the way back to it. -->
				{#if ghostAt}
					<button
						type="button"
						aria-hidden="true"
						tabindex="-1"
						onclick={() => turn(-1)}
						onpointerenter={() => (hot = 'prev')}
						onpointerleave={() => (hot = null)}
						class="absolute inset-y-0 start-0 z-10 flex items-center justify-end pe-1"
						style="width: {Math.max(0, ghostAt.cx + ghostAt.pr)}px"
					>
						<ChevronLeftIcon
							class="size-5 transition-colors {hot === 'prev' ? 'text-white' : 'text-white/50'}"
						/>
					</button>
				{/if}
				<!-- On a dark pill: the body behind it is lit. -->
				<button
					type="button"
					onclick={() => turn(-1)}
					onpointerenter={() => (hot = 'prev')}
					onpointerleave={() => (hot = null)}
					aria-label={m.search_prev_page()}
					class="absolute start-5 z-10 flex h-8 items-center gap-1.5 rounded-lg px-2 text-[11.5px] transition-colors {hot ===
					'prev'
						? 'bg-black/80 text-white'
						: 'bg-black/55 text-white/70'}"
					style="bottom: {LABEL_ROW + 14}px"
				>
					<ChevronLeftIcon class="size-3.5" />
					<span
						>{ghost.name} · {narrow ? '' : `${sizeText(ghost)} · `}{m.compare_page_of({
							n: pageIndex
						})}</span
					>
				</button>
			{/if}

			{#if speck && speckAt}
				<!-- At true size it is a few pixels across, so the reach for it is
				     the width of the strip it sits in. -->
				<button
					type="button"
					aria-hidden="true"
					tabindex="-1"
					onclick={() => turn(1)}
					onpointerenter={() => (hot = 'next')}
					onpointerleave={() => (hot = null)}
					class="absolute inset-y-0 z-10 flex items-center justify-start ps-1"
					style="left: {speckAt.cx - 4}px; width: 44px"
				>
					<ChevronRightIcon
						class="size-5 translate-y-8 transition-colors {hot === 'next'
							? 'text-white'
							: 'text-white/50'}"
					/>
				</button>
				{#if !narrow}
					<button
						type="button"
						onclick={() => turn(1)}
						onpointerenter={() => (hot = 'next')}
						onpointerleave={() => (hot = null)}
						aria-label={m.search_next_page()}
						class="absolute end-5 z-10 flex h-8 items-center gap-1.5 rounded-lg px-2 text-[11.5px] transition-colors {hot ===
						'next'
							? 'bg-black/80 text-white'
							: 'bg-black/55 text-white/70'}"
						style="bottom: {LABEL_ROW + 14}px"
					>
						<span>{speck.name} · {sizeText(speck)} · {m.compare_page_of({ n: pageIndex + 2 })}</span
						>
						<ChevronRightIcon class="size-3.5" />
					</button>
				{/if}
			{/if}

			{#if scaleBar}
				<!-- Bottom centre, between the page links; a phone has no room there. -->
				<div
					class="pointer-events-none absolute flex flex-col gap-1 {narrow
						? 'start-5 top-5 items-start'
						: 'left-1/2 -translate-x-1/2 items-center'}"
					style={narrow ? '' : `bottom: ${LABEL_ROW + 14}px`}
				>
					<div
						class="h-[7px] border-x border-b border-white/40"
						style="width: {scaleBar.px}px"
					></div>
					<span class="text-[11px] text-white/60 tabular-nums">{scaleBar.label}</span>
				</div>
			{/if}

			{#if bands.length > 1 && narrow}
				<!-- The phone has no next-page link, only the strip, so it counts pages. -->
				<div
					role="group"
					aria-label={m.compare_pages_label({ n: pageIndex + 1, total: bands.length })}
					class="pointer-events-none absolute left-1/2 flex -translate-x-1/2 gap-1.5"
					style="bottom: {LABEL_ROW + 16}px"
				>
					{#each bands.map((_, i) => i) as i (i)}
						<span class="size-[7px] rounded-full {i === pageIndex ? 'bg-white/85' : 'bg-white/30'}"
						></span>
					{/each}
				</div>
			{/if}

			{#if !railOpen && !narrow}
				<button
					type="button"
					aria-label={m.compare_show_list()}
					aria-expanded="false"
					onclick={() => (railOpen = true)}
					class="absolute start-5 top-5 flex size-11 items-center justify-center rounded-xl border border-white/15 bg-black/70 text-white backdrop-blur-sm hover:bg-black/85"
				>
					<MenuIcon class="size-[18px]" />
				</button>
			{/if}
		</div>

		{#if narrow}
			<!-- No drawer on a phone: the row keeps the screen, and the set is
			     changed from the two controls over it. -->
			<div class="pointer-events-none absolute inset-x-0 top-3 flex justify-end gap-2 px-3">
				<Popover.Root bind:open={pickerOpen}>
					<Popover.Trigger
						class="pointer-events-auto flex h-10 items-center gap-2 rounded-xl border border-white/15 bg-black/70 px-3 text-[13px] text-white backdrop-blur-sm"
					>
						<ListIcon class="size-4" />
						{m.compare_object_count({ count: objects.length })}
					</Popover.Trigger>
					<Popover.Content side="bottom" align="end" sideOffset={8} class="w-[330px] p-0">
						<ComparePicker chosen={selected} onadd={addHit} onpreset={togglePreset} />
					</Popover.Content>
				</Popover.Root>
			</div>

			<button
				type="button"
				aria-label={m.compare_add()}
				onclick={() => (pickerOpen = true)}
				style="bottom: {LABEL_ROW + 16}px"
				class="absolute end-5 flex size-14 items-center justify-center rounded-2xl bg-white text-black shadow-lg"
			>
				<PlusIcon class="size-6" />
			</button>
		{/if}

		{#if menu && menuObject}
			<!-- Right click on a body: go to it, or drop it. -->
			<div
				class="fixed z-50 flex w-52 flex-col rounded-xl border border-border bg-popover p-1.5 shadow-xl"
				style="left: {Math.min(menu.x, innerWidth - 220)}px; top: {menu.y}px"
			>
				<a
					href={bodyHref(menuObject.id, menuObject.name)}
					class="flex h-9 items-center gap-2.5 rounded-lg px-2.5 text-[13px] hover:bg-accent"
				>
					<ExternalLinkIcon class="size-3.5" />
					{m.compare_open({ name: menuObject.name })}
				</a>
				<button
					type="button"
					onclick={() => remove(menuObject.id)}
					class="flex h-9 items-center gap-2.5 rounded-lg px-2.5 text-start text-[13px] hover:bg-accent"
				>
					<XIcon class="size-3.5" />
					{m.compare_remove_short()}
				</button>
			</div>
			<!-- One click anywhere else closes it. -->
			<button
				type="button"
				tabindex="-1"
				aria-label={m.close()}
				onclick={() => (menu = null)}
				class="fixed inset-0 z-40 cursor-default"
			></button>
		{/if}
	</div>
</div>
