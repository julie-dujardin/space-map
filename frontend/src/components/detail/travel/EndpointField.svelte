<!--
  An endpoint box: closed it summarises where you start or arrive and how; open
  it is a popover asking those two questions in that order.

  Where comes first, because how you arrive is a question about somewhere — and
  because the orbits on offer are a fact about the body, so there is nothing to
  list until one is chosen. Reopening a box that already has a body lands back
  on the search with a line down to the orbits: changing the destination and
  changing the orbit are both one gesture from here.

  A surface feature answers both at once. There is no way to reach a named
  crater except by landing in it, so its box never shows the second step.
-->
<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import ChevronDownIcon from '@lucide/svelte/icons/chevron-down';
	import ChevronLeftIcon from '@lucide/svelte/icons/chevron-left';
	import ChevronRightIcon from '@lucide/svelte/icons/chevron-right';
	import MapPinIcon from '@lucide/svelte/icons/map-pin';
	import * as Popover from '$lib/components/ui/popover/index.js';
	import { ScrollArea } from '$lib/components/ui/scroll-area/index.js';
	import { formatKm } from '$lib/format/distance';
	import { formatDuration } from '$lib/format/duration';
	import { formatDvBrief } from '$lib/travel/format';
	import type { EndpointMode } from '$lib/travel/trip';
	import type { OrbitChoice, OrbitGroup } from '$lib/travel/orbits';
	import type { TravelEndpointPick } from '$lib/travel/endpoint';
	import EndpointSearch from './EndpointSearch.svelte';

	interface Props {
		/** Origins get a hollow dot; destinations get a pin. */
		role: 'origin' | 'target';
		/** Null when this end has not been chosen yet. */
		bodyName: string | null;
		/** Shown in place of a name, greyed, when there isn't one. */
		placeholder?: string;
		/** This end is a named place on a surface — mode is fixed to landing. */
		isFeature?: boolean;
		mode: EndpointMode;
		onModeChange: (mode: EndpointMode) => void;
		/** Every way this end can be met. Empty until the body is measured. */
		choices: OrbitChoice[];
		/** Altitude of the custom orbit, km, and how high it may go. */
		customAltKm: number;
		maxAltKm: number;
		onCustomAlt: (km: number) => void;
		/** Δv this choice costs at this end, km/s — null while nothing is priced. */
		priceKms?: (choice: OrbitChoice) => number | null;
		open: boolean;
		onOpenChange: (open: boolean) => void;
		/** Bodies this end may not be. */
		excludeIds: ReadonlySet<string>;
		onPick: (pick: TravelEndpointPick) => void;
	}
	let {
		role,
		bodyName,
		placeholder = '',
		isFeature = false,
		mode,
		onModeChange,
		choices,
		customAltKm,
		maxAltKm,
		onCustomAlt,
		priceKms,
		open,
		onOpenChange,
		excludeIds,
		onPick
	}: Props = $props();

	const MODE_LABELS: Record<EndpointMode, () => string> = {
		surface: () => (role === 'origin' ? m.travel_mode_surface() : m.travel_mode_landing()),
		'low-orbit': () => m.travel_mode_low_orbit(),
		elliptical: () => m.travel_mode_elliptical(),
		'semi-sync': () => m.travel_mode_semi_sync(),
		stationary: () => m.travel_mode_stationary(),
		transfer: () => m.travel_mode_transfer(),
		heo: () => m.travel_mode_heo(),
		custom: () => m.travel_mode_custom(),
		flyby: () => m.travel_mode_flyby()
	};

	const GROUP_LABELS: Record<OrbitGroup, () => string> = {
		land: () => m.travel_orbit_group_land(),
		orbit: () => m.travel_mode_orbit(),
		pass: () => m.travel_orbit_group_pass()
	};

	/** Which step is showing. A box with no body has only one. */
	let step = $state<'where' | 'how'>('where');

	// Closing puts the box back at its first step: the next time it opens is a
	// new question, not the tail of the last one.
	$effect(() => {
		if (!open) step = 'where';
	});

	let showMode = $derived(bodyName !== null && !isFeature && choices.length > 0);
	let chosen = $derived(choices.find((c) => c.kind === mode));
	/**
	 * The altitude a custom orbit is actually at, km.
	 *
	 * Not the number in the trip: a body holds only so much room, and one asking
	 * for more than that is met at the ceiling. Showing what was asked for would
	 * put a different altitude on the row than the one being priced.
	 */
	let customAltShown = $derived(
		chosen?.kind === 'custom' ? (chosen.periAltKm ?? customAltKm) : customAltKm
	);
	// Closed, "custom altitude" says nothing; the altitude itself says all of it.
	let modeLabel = $derived(
		mode === 'custom'
			? m.travel_orbit_at({ altitude: formatKm(customAltShown) })
			: MODE_LABELS[mode]()
	);

	// Every orbit the body can hold, all at once: there are at most nine, the
	// column is tall enough for them, and a fold would hide the one comparison
	// the Δv column exists to make.
	let groups = $derived(
		(['land', 'orbit', 'pass'] as OrbitGroup[])
			.map((group) => ({ group, items: choices.filter((c) => c.group === group) }))
			.filter((g) => g.items.length > 0)
	);

	/** Altitude, or the two ends of an ellipse — what the choice is made in. */
	function detailOf(choice: OrbitChoice): string {
		if (choice.periAltKm === undefined || choice.apoAltKm === undefined) return '';
		return choice.periAltKm === choice.apoAltKm
			? m.travel_orbit_circular({ altitude: formatKm(choice.periAltKm) })
			: m.travel_orbit_ellipse({
					periapsis: formatKm(choice.periAltKm),
					apoapsis: formatKm(choice.apoAltKm)
				});
	}

	function choose(choice: OrbitChoice) {
		onModeChange(choice.kind);
		// A slider still being dragged is not a decision made.
		if (choice.kind !== 'custom') onOpenChange(false);
	}
</script>

<Popover.Root {open} onOpenChange={(next: boolean) => onOpenChange(next)}>
	<Popover.Trigger
		class="border-border/60 bg-muted/40 hover:bg-muted data-[state=open]:bg-background flex w-full items-center gap-2.5 rounded-md border px-2.5 py-2 text-start transition-colors"
	>
		<!-- The dot and the pin carry which end this is on screen, so the words go
		     to the accessible name instead of taking a line of their own. -->
		<span class="sr-only">{role === 'origin' ? m.travel_from() : m.travel_to()}</span>
		<!-- Both markers sit in the same box so the two fields' text lines up. -->
		<span class="flex size-3.5 shrink-0 items-center justify-center">
			{#if role === 'origin'}
				<span class="border-muted-foreground size-2 rounded-full border-2"></span>
			{:else}
				<MapPinIcon class="text-foreground size-3.5" />
			{/if}
		</span>
		<span class="min-w-0 flex-1">
			<span class="block truncate text-sm font-medium {bodyName ? '' : 'text-muted-foreground'}">
				{bodyName ?? placeholder}
			</span>
			{#if showMode}
				<span class="text-muted-foreground block truncate text-[11px]">{modeLabel}</span>
			{/if}
		</span>
		<ChevronDownIcon class="text-muted-foreground size-4 shrink-0" />
	</Popover.Trigger>

	<Popover.Content align="start" sideOffset={6} class="w-[20rem] gap-0 p-2">
		{#if step === 'where' || !showMode}
			<EndpointSearch {excludeIds} {onPick} />

			{#if showMode}
				<!-- Reopening the box usually means adjusting the orbit rather than
				     moving the trip, so the second step is one line away. -->
				<button
					type="button"
					onclick={() => (step = 'how')}
					class="border-border/60 text-muted-foreground hover:text-foreground mt-2 flex w-full items-center gap-2 border-t pt-2 text-start text-[11px]"
				>
					<span class="shrink-0 uppercase">
						{role === 'origin' ? m.travel_departure_mode() : m.travel_arrival_mode()}
					</span>
					<span class="text-foreground truncate">{modeLabel}</span>
					<ChevronRightIcon class="ms-auto size-3.5 shrink-0" />
				</button>
			{/if}
		{:else}
			<div class="border-border/60 mb-2 flex items-center gap-2 border-b pb-2">
				<button
					type="button"
					onclick={() => (step = 'where')}
					class="text-muted-foreground hover:text-foreground flex min-w-0 items-center gap-1 text-xs"
				>
					<ChevronLeftIcon class="size-3.5 shrink-0" />
					<span class="truncate">{bodyName}</span>
				</button>
				<span class="text-muted-foreground ms-auto shrink-0 text-[10px] uppercase">
					{role === 'origin' ? m.travel_departure_mode() : m.travel_arrival_mode()}
				</span>
			</div>

			<ScrollArea viewportClasses="max-h-[26rem]">
				<div class="flex flex-col gap-2 pe-2">
					{#each groups as { group, items } (group)}
						<div class="flex flex-col">
							<p class="text-muted-foreground px-1 pb-1 text-[10px] tracking-wide uppercase">
								{GROUP_LABELS[group]()}
							</p>
							{#each items as choice (choice.kind)}
								{@const active = choice.kind === mode}
								{@const dv = priceKms?.(choice) ?? null}
								<button
									type="button"
									onclick={() => choose(choice)}
									aria-pressed={active}
									class="hover:bg-muted flex flex-col gap-0.5 rounded-md px-2 py-1.5 text-start {active
										? 'bg-muted'
										: ''}"
								>
									<span class="flex w-full items-baseline gap-2">
										<span class="flex-1 truncate text-xs font-medium">
											{MODE_LABELS[choice.kind]()}
										</span>
										{#if dv !== null}
											<span class="text-muted-foreground shrink-0 text-[10px] tabular-nums">
												{formatDvBrief(dv)}
											</span>
										{/if}
									</span>
									{#if choice.periodHours !== undefined}
										<span
											class="text-muted-foreground flex w-full items-baseline gap-1.5 text-[10px]"
										>
											<span class="truncate">{detailOf(choice)}</span>
											<span class="opacity-60">·</span>
											<span class="shrink-0">{formatDuration(choice.periodHours / 24)}</span>
										</span>
									{/if}
								</button>

								{#if active && choice.kind === 'custom'}
									<div class="flex items-center gap-2 px-2 pt-1 pb-2">
										<input
											type="range"
											min={1}
											max={Math.round(maxAltKm)}
											value={customAltShown}
											oninput={(e) => onCustomAlt(Number(e.currentTarget.value))}
											class="accent-primary h-1 flex-1"
											aria-label={m.travel_orbit_altitude()}
										/>
										<span
											class="text-muted-foreground w-20 shrink-0 text-end text-[10px] tabular-nums"
										>
											{formatKm(customAltShown)}
										</span>
									</div>
								{/if}
							{/each}
						</div>
					{/each}
				</div>
			</ScrollArea>
		{/if}
	</Popover.Content>
</Popover.Root>
