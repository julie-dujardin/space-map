<!--
  The Δv subway map: the origin's trunk and one line per destination, every
  stop a link into the planner for that trip. Rows down the page on a wide
  screen, one strip scrolled sideways on a phone.
-->
<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import ChevronDownIcon from '@lucide/svelte/icons/chevron-down';
	import ChevronRightIcon from '@lucide/svelte/icons/chevron-right';
	import ListIcon from '@lucide/svelte/icons/list';
	import * as m from '$lib/paraglide/messages.js';
	import SitePage from '../../components/nav/SitePage.svelte';
	import { SITE_GUTTER } from '../../components/nav/site';
	import SubwayDiagram from '../../components/nav/SubwayDiagram.svelte';
	import BodySearch from '../../components/nav/BodySearch.svelte';
	import * as Popover from '$lib/components/ui/popover/index.js';
	import * as Sheet from '$lib/components/ui/sheet/index.js';
	import { ScrollArea } from '$lib/components/ui/scroll-area/index.js';
	import { Button } from '$lib/components/ui/button/index.js';
	import { isSearchEnabled } from '$lib/search/client';
	import { formatNavEnd } from '$lib/state/nav-end';
	import { formatDv, formatDvFigure } from '$lib/travel/format';
	import { drawRows, drawStrip, type DrawText } from '$lib/travel/subway-draw';
	import { buildTree, type TreeStop } from '$lib/travel/subway-tree';
	import { DEFAULT_TRIP, serializeTripSuffix, type EndpointMode } from '$lib/travel/trip';

	let { data } = $props();

	const map = $derived(data.map);
	const names = $derived(data.names);
	const tree = $derived(buildTree(map, names, data.colors));

	function name(id: string): string {
		return names[id] ?? id;
	}

	const text: DrawText = $derived({
		stop: {
			transfer: m.delta_v_stop_intercept(),
			escape: m.delta_v_stop_capture(),
			orbit: m.travel_mode_low_orbit(),
			surface: m.delta_v_station_surface(),
			stationary: m.travel_mode_stationary()
		},
		hint: {
			transfer: m.delta_v_hint_intercept(),
			escape: m.delta_v_hint_capture(),
			orbit: m.delta_v_hint_low_orbit()
		},
		escape: m.delta_v_station_escape(),
		gto: m.travel_mode_transfer(),
		totals: m.travel_total_dv(),
		rootEscape: m.delta_v_solar_escape()
	});

	/** The planner opened on the trip a stop stands for: origin to the row's
	 *  body, ending the way the stop says. A trunk stop only sets the departure. */
	function plannerHref(stop: TreeStop, targetId: string): string | null {
		const onTrunk = targetId === map.originId && tree.trunk.some((t) => t.station === stop.station);
		const origin: EndpointMode = onTrunk
			? (stop.mode ?? DEFAULT_TRIP.ends.origin.mode)
			: DEFAULT_TRIP.ends.origin.mode;
		const target: EndpointMode = onTrunk
			? DEFAULT_TRIP.ends.target.mode
			: (stop.mode ?? DEFAULT_TRIP.ends.target.mode);
		const trip = {
			...DEFAULT_TRIP,
			ends: {
				origin: { ...DEFAULT_TRIP.ends.origin, mode: origin },
				target: { ...DEFAULT_TRIP.ends.target, mode: target }
			}
		};
		const path = resolve('/nav/[[from]]/[[to]]', {
			from: formatNavEnd(map.originId, null),
			to: onTrunk ? undefined : formatNavEnd(targetId, null)
		});
		return `${path}?at=now${serializeTripSuffix(trip)}`;
	}

	const draw = $derived({
		tree,
		text,
		fmt: formatDvFigure,
		fmtTotal: formatDv,
		link: plannerHref
	});
	const rows = $derived(drawRows(draw));
	const strip = $derived(drawStrip(draw));

	/** Every body on offer, for the origin picker: the origin first. */
	const bodies = $derived(
		[map.originId, ...data.systems.flatMap((s) => s.members)].map((id) => ({ id, name: name(id) }))
	);
	const visible = $derived(new Set(data.visible));

	/** The page for an origin, a set of switched-off bodies, and the
	 *  destinations asked for beyond the default set. */
	function pageHref(
		from: string,
		hidden: readonly string[],
		extra: readonly string[] = data.extra
	): string {
		const query = new URLSearchParams({ from });
		if (hidden.length) query.set('hide', hidden.join(','));
		if (extra.length) query.set('to', extra.join(','));
		return `${resolve('/nav')}?${query}`;
	}

	function pickOrigin(event: Event): void {
		goto(pageHref((event.currentTarget as HTMLSelectElement).value, data.hidden));
	}

	/** The page with one more destination on it, switched on: a body found by
	 *  search is wanted drawn, whatever the reader last hid. */
	function addTargetHref(id: string): string {
		const extra = data.extra.includes(id) ? data.extra : [...data.extra, id];
		return pageHref(
			map.originId,
			data.hidden.filter((hidden) => hidden !== id),
			extra
		);
	}

	const searchEnabled = isSearchEnabled();
	let originOpen = $state(false);

	/** Bodies the origin search should not offer: the origin it would replace. */
	const originExclude = $derived(new Set([map.originId]));
	/** Bodies the target search should not offer: what is already drawn, and the
	 *  origin, which is never a destination. */
	const targetExclude = $derived(new Set([map.originId, ...data.visible]));

	/** Destinations on the map that the kernel could not route to. They are
	 *  simply absent from the drawing, so say so rather than leave a pick with
	 *  no visible effect. */
	const unrouted = $derived.by(() => {
		if (data.failed) return [];
		const routed = new Set(map.routes.map((route) => route.targetId));
		return data.visible.filter((id) => !routed.has(id));
	});

	/** Switch bodies on or off: the map is rewritten with the new set. */
	function setVisible(ids: readonly string[], on: boolean): void {
		const next = on
			? data.hidden.filter((id) => !ids.includes(id))
			: [...data.hidden, ...ids.filter((id) => !data.hidden.includes(id))];
		goto(pageHref(map.originId, next));
	}

	/** What to call a system: its body under the Sun, unless that body is not
	 *  on offer (the origin, say) and one moon stands alone. */
	function systemLabelId(system: { id: string; members: string[] }): string {
		if (system.members.includes(system.id) || system.members.length !== 1) return system.id;
		return system.members[0];
	}

	/** How much of a system is drawn: none, some, or all of it. */
	function systemState(members: readonly string[]): 'none' | 'some' | 'all' {
		const on = members.filter((id) => visible.has(id)).length;
		return on === 0 ? 'none' : on === members.length ? 'all' : 'some';
	}

	let drawerOpen = $state(false);
	let expanded = $state(new Set<string>());

	function toggleExpanded(id: string): void {
		const next = new Set(expanded);
		if (next.has(id)) next.delete(id);
		else next.add(id);
		expanded = next;
	}
</script>

<svelte:head>
	<title>{m.nav_delta_v()} - {m.page_title()}</title>
</svelte:head>

<!-- Bleeding, so the strip gets the whole width; everything else guttered. -->
<SitePage current="nav" title={m.nav_delta_v()} bleed>
	<!-- The origin picker outlives a failure: an origin the catalogue cannot
	     place routes nowhere, and changing it is the only way back. -->
	<div class="{SITE_GUTTER} mb-6 flex flex-wrap items-center gap-3">
		{#if searchEnabled}
			<!-- Search over the whole catalogue, with the bodies already drawn listed
			     under it: the usual origin still needs no typing. -->
			<div class="flex items-center gap-2 text-sm text-muted-foreground">
				<span id="nav-origin-label">{m.travel_from()}</span>
				<Popover.Root bind:open={originOpen}>
					<Popover.Trigger
						aria-labelledby="nav-origin-label"
						class="flex h-9 min-w-36 items-center justify-between gap-2 rounded-lg border border-border bg-background px-3 text-sm font-medium text-foreground"
					>
						{name(map.originId)}
						<ChevronDownIcon class="size-4 text-muted-foreground" />
					</Popover.Trigger>
					<Popover.Content
						align="start"
						sideOffset={6}
						class="w-[20rem] max-w-[calc(100vw-2rem)] gap-0 p-2"
					>
						<BodySearch
							label={m.travel_from()}
							excludeIds={originExclude}
							names={data.names}
							hrefFor={(id) => pageHref(id, data.hidden)}
							onNavigate={() => (originOpen = false)}
						>
							{#snippet browse()}
								<ScrollArea viewportClasses="max-h-56">
									<ul class="flex flex-col">
										{#each bodies as body (body.id)}
											<li>
												<a
													href={pageHref(body.id, data.hidden)}
													onclick={() => (originOpen = false)}
													aria-current={body.id === map.originId ? 'true' : undefined}
													class="block truncate rounded-md px-2 py-1.5 text-xs hover:bg-muted {body.id ===
													map.originId
														? 'bg-muted font-medium'
														: ''}"
												>
													{body.name}
												</a>
											</li>
										{/each}
									</ul>
								</ScrollArea>
							{/snippet}
						</BodySearch>
					</Popover.Content>
				</Popover.Root>
			</div>
		{:else}
			<label class="flex items-center gap-2 text-sm text-muted-foreground">
				{m.travel_from()}
				<select
					class="h-9 min-w-36 rounded-lg border border-border bg-background px-3 text-sm font-medium text-foreground"
					value={map.originId}
					onchange={pickOrigin}
				>
					{#each bodies as body (body.id)}
						<option value={body.id}>{body.name}</option>
					{/each}
				</select>
			</label>
		{/if}
		{#if !data.failed}
			<Sheet.Root bind:open={drawerOpen}>
				<Sheet.Trigger>
					{#snippet child({ props })}
						<Button {...props} variant="outline" size="sm" class="ms-auto">
							<ListIcon />
							{m.tab_targets()}
						</Button>
					{/snippet}
				</Sheet.Trigger>
				<Sheet.Content side="right" class="overflow-y-auto">
					<Sheet.Header>
						<Sheet.Title>{m.tab_targets()}</Sheet.Title>
					</Sheet.Header>
					<!-- The list below is planets and large moons; any other destination
					     is found rather than browsed for. -->
					{#if searchEnabled}
						<div class="mb-3 border-b border-border/60 px-4 pb-3">
							<BodySearch
								label={m.delta_v_add_target()}
								excludeIds={targetExclude}
								names={data.names}
								hrefFor={addTargetHref}
								onNavigate={() => (drawerOpen = false)}
							/>
						</div>
					{/if}
					<ul class="flex flex-col px-4">
						{#each data.systems as system (system.id)}
							{@const state = systemState(system.members)}
							{@const open = expanded.has(system.id)}
							{@const labelId = systemLabelId(system)}
							<li>
								<div class="flex h-9 items-center gap-1">
									{#if system.members.length > 1}
										<button
											type="button"
											class="flex size-7 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
											aria-expanded={open}
											aria-label={m.tab_members()}
											onclick={() => toggleExpanded(system.id)}
										>
											<ChevronRightIcon
												class="size-4 transition-transform {open ? 'rotate-90' : ''}"
											/>
										</button>
									{:else}
										<span class="size-7"></span>
									{/if}
									<label class="flex flex-grow items-center gap-3 text-sm font-medium">
										<input
											type="checkbox"
											checked={state === 'all'}
											indeterminate={state === 'some'}
											onchange={(e) => setVisible(system.members, e.currentTarget.checked)}
										/>
										<span
											class="size-2.5 rounded-full"
											style="background: {data.colors[labelId] ?? 'currentColor'}"
										></span>
										{name(labelId)}
									</label>
								</div>
								{#if open && system.members.length > 1}
									<ul class="mb-1 flex flex-col ps-8">
										{#each system.members as id (id)}
											<li>
												<label class="flex h-8 items-center gap-3 text-sm">
													<input
														type="checkbox"
														checked={visible.has(id)}
														onchange={(e) => setVisible([id], e.currentTarget.checked)}
													/>
													<span
														class="size-2.5 rounded-full"
														style="background: {data.colors[id] ?? 'currentColor'}"
													></span>
													{name(id)}
												</label>
											</li>
										{/each}
									</ul>
								{/if}
							</li>
						{/each}
					</ul>
					{#if data.hidden.length}
						<a
							class="px-4 text-sm text-muted-foreground hover:text-foreground"
							href={pageHref(map.originId, [])}
						>
							{m.delta_v_reset_targets()}
						</a>
					{/if}
				</Sheet.Content>
			</Sheet.Root>
		{/if}
	</div>

	{#if unrouted.length}
		<!-- A destination with no route is simply absent from the drawing, so a
		     pick that landed on one would otherwise look like nothing happened. -->
		<p class="{SITE_GUTTER} mb-4 text-sm text-muted-foreground">
			{m.delta_v_no_route({ bodies: unrouted.map(name).join(', ') })}
		</p>
	{/if}

	{#if data.failed}
		<p class="{SITE_GUTTER} text-sm text-muted-foreground">{m.delta_v_error()}</p>
	{:else}
		<!-- Rows on a wide screen; on a phone the strip, scrolled sideways. -->
		<div class="{SITE_GUTTER} hidden md:block">
			<SubwayDiagram drawing={rows} label={m.nav_delta_v()} />
		</div>
		<!-- The level names are pinned to the left edge while the map scrolls
		     under them, so the rungs are always named. -->
		<div class="flex md:hidden">
			<div class="shrink-0">
				<SubwayDiagram drawing={strip.legend} fixed />
			</div>
			<div class="overflow-x-auto">
				<SubwayDiagram drawing={strip.map} fixed label={m.nav_delta_v()} />
			</div>
		</div>
	{/if}
</SitePage>
