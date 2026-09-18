<!--
  The Δv subway map: the origin's trunk and one line per destination, every
  stop a link into the planner for that trip. Rows down the page on a wide
  screen, one strip scrolled sideways on a phone.
-->
<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import ChevronRightIcon from '@lucide/svelte/icons/chevron-right';
	import ListIcon from '@lucide/svelte/icons/list';
	import * as m from '$lib/paraglide/messages.js';
	import SitePage from '../../components/nav/SitePage.svelte';
	import SubwayDiagram from '../../components/nav/SubwayDiagram.svelte';
	import * as Sheet from '$lib/components/ui/sheet/index.js';
	import { Button } from '$lib/components/ui/button/index.js';
	import { formatNavEnd } from '$lib/state/nav-end';
	import { bodyHref } from '$lib/state/url';
	import { formatDvFigure } from '$lib/travel/format';
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

	const rows = $derived(drawRows({ tree, text, fmt: formatDvFigure, link: plannerHref }));
	const strip = $derived(drawStrip({ tree, text, fmt: formatDvFigure, link: plannerHref }));

	/** Every body on offer, for the origin picker: the origin first. */
	const bodies = $derived(
		[map.originId, ...data.systems.flatMap((s) => s.members)].map((id) => ({ id, name: name(id) }))
	);
	const visible = $derived(new Set(data.visible));

	/** The page for an origin and a set of switched-off bodies; what a link
	 *  asked for on top rides along. */
	function pageHref(from: string, hidden: readonly string[]): string {
		const query = new URLSearchParams({ from });
		if (hidden.length) query.set('hide', hidden.join(','));
		if (data.extra.length) query.set('to', data.extra.join(','));
		return `${resolve('/nav')}?${query}`;
	}

	function pickOrigin(event: Event): void {
		goto(pageHref((event.currentTarget as HTMLSelectElement).value, data.hidden));
	}

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

<SitePage current="nav" title={m.nav_delta_v()}>
	{#if data.failed}
		<p class="text-sm text-muted-foreground">{m.delta_v_error()}</p>
	{:else}
		<div class="mb-6 flex flex-wrap items-center gap-3">
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
			<a
				class="text-sm text-muted-foreground hover:text-foreground"
				href={bodyHref(map.originId, name(map.originId))}
			>
				{name(map.originId)} →
			</a>
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
						<Sheet.Description>{m.delta_v_targets_hint()}</Sheet.Description>
					</Sheet.Header>
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
		</div>

		<!-- Rows on a wide screen; on a phone the strip, scrolled sideways. -->
		<div class="hidden md:block">
			<SubwayDiagram drawing={rows} />
		</div>
		<div class="md:hidden">
			<p class="mb-2 text-xs text-muted-foreground">{m.delta_v_scroll_hint()}</p>
			<div class="-mx-6 overflow-x-auto px-6">
				<SubwayDiagram drawing={strip} fixed />
			</div>
		</div>

		<dl class="mt-8 flex flex-col gap-2 text-xs text-muted-foreground">
			<div class="flex items-center gap-3">
				<svg width="16" height="16" viewBox="0 0 16 16" class="shrink-0 text-foreground">
					<circle cx="8" cy="8" r="5" fill="none" stroke="currentColor" stroke-width="3" />
				</svg>
				<dd>{m.delta_v_legend_stop()}</dd>
			</div>
			<div class="flex items-center gap-3">
				<svg width="16" height="10" viewBox="0 0 16 10" class="shrink-0">
					<path d="M2,9 a6,6 0 0 1 12,0" fill="none" stroke-width="2" class="stroke-sky-500" />
				</svg>
				<dd>{m.travel_aero_absorbed()}</dd>
			</div>
			<dd>{m.travel_total_dv()}: {m.delta_v_to_orbit()} · {m.travel_aerobraked()}</dd>
			<dd>{m.delta_v_legend_note()}</dd>
		</dl>
	{/if}
</SitePage>
