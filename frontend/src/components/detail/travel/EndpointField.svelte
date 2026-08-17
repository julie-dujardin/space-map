<!--
  An endpoint box: step 1 picks the place, step 2 the mode. Orbits depend on
  the body, so step 2 waits for one; a surface feature fixes the mode, so it
  skips step 2. A pad also fixes the mode, but a range holds dozens with no
  default, so its step 2 lists pads instead of orbits.

  On a phone both steps take the whole screen instead of a popover, the way the
  map's own search does — a search over the whole catalogue has nowhere to grow
  inside a card the width of the drawer that opened it.
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
	import type { LaunchPad } from '$lib/travel/launch-pad';
	import EndpointSearch from './EndpointSearch.svelte';
	import FullscreenPicker from './FullscreenPicker.svelte';
	import { endpointModeLabel } from './endpoint-labels';

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
		/** Pads this end may stand on; empty otherwise. */
		pads?: readonly LaunchPad[];
		/** Which of them it stands on now, by GCAT code. */
		padCode?: string | null;
		/** Line shown under the name when grounded — pad name, or coordinates. Null otherwise. */
		groundLine?: string | null;
		onPadPick?: (pad: LaunchPad) => void;
		/** Take the whole screen rather than open a popover — the phone layout. */
		fullscreen?: boolean;
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
		onPick,
		pads = [],
		padCode = null,
		groundLine = null,
		onPadPick,
		fullscreen = false
	}: Props = $props();

	/** Shared by both presentations, so the closed field looks the same either way. */
	const TRIGGER =
		'border-border/60 bg-muted/40 hover:bg-muted flex w-full items-center gap-2.5 rounded-md border px-2.5 py-2 text-start transition-colors';

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

	/** Whether there's a second step, and which: a pad end has no orbits, others have no pads. */
	let showPads = $derived(pads.length > 1 && onPadPick !== undefined);
	let showStepTwo = $derived(showPads || (bodyName !== null && !isFeature && choices.length > 0));
	let chosen = $derived(choices.find((c) => c.kind === mode));
	/** The priced altitude, in km. A too high request decreases to the maximum. */
	let customAltShown = $derived(
		chosen?.kind === 'custom' ? (chosen.periAltKm ?? customAltKm) : customAltKm
	);
	// The closed box shows the height. The words "custom altitude" give no data.
	let modeLabel = $derived(endpointModeLabel(mode, role, customAltShown));
	// Pad site is what distinguishes a range; a single-place range says it once, up top.
	let padPlaces = $derived(new Set(pads.map((p) => p.siteName)).size);

	/** What the closed box says under the name, if anything. */
	let subLine = $derived(groundLine ?? (showStepTwo ? modeLabel : null));

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

	/**
	 * A place chosen, and then the way to meet it.
	 *
	 * Moving on is optimistic: the new body's orbits are still being measured
	 * when the pick lands, so this cannot wait on `showStepTwo`. A body that
	 * turns out to have no second step falls back to the search below, and a
	 * named place answers "how" by itself, so it stays put and the panel closes
	 * the box.
	 */
	function picked(pick: TravelEndpointPick) {
		onPick(pick);
		if (pick.featureId === null) step = 'how';
	}

	function choose(choice: OrbitChoice) {
		onModeChange(choice.kind);
		// A slider still being dragged is not a decision made.
		if (choice.kind !== 'custom') onOpenChange(false);
	}
</script>

{#snippet triggerBody()}
	<!-- Dot/pin already show which end this is; the words go to the accessible name instead. -->
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
		{#if subLine}
			<span class="text-muted-foreground block truncate text-[11px]">{subLine}</span>
		{/if}
	</span>
	<ChevronDownIcon class="text-muted-foreground size-4 shrink-0" />
{/snippet}

{#snippet panel()}
	{#if step === 'where' || !showStepTwo}
		<EndpointSearch
			label={role === 'origin' ? m.travel_from() : m.travel_to()}
			{excludeIds}
			onPick={picked}
			{fullscreen}
		/>

		{#if showStepTwo}
			<!-- Reopening usually means adjusting the orbit, not moving the trip, so step 2 is one line away. -->
			<button
				type="button"
				onclick={() => (step = 'how')}
				class="border-border/60 text-muted-foreground hover:text-foreground mt-2 flex w-full shrink-0 items-center gap-2 border-t pt-2 text-start text-[11px]"
			>
				<span class="shrink-0 text-[10px] tracking-wide uppercase">
					{showPads
						? m.travel_launch_pad()
						: role === 'origin'
							? m.travel_departure_mode()
							: m.travel_arrival_mode()}
				</span>
				<span class="text-foreground truncate">{subLine}</span>
				<ChevronRightIcon class="ms-auto size-3.5 shrink-0" />
			</button>
		{/if}
	{:else}
		<div class="border-border/60 mb-2 flex shrink-0 items-center gap-2 border-b pb-2">
			<button
				type="button"
				onclick={() => (step = 'where')}
				class="text-muted-foreground hover:text-foreground flex min-w-0 items-center gap-1 text-xs"
			>
				<ChevronLeftIcon class="size-3.5 shrink-0" />
				<span class="truncate">{bodyName}</span>
			</button>
			<span class="text-muted-foreground ms-auto shrink-0 text-[10px] tracking-wide uppercase">
				{showPads
					? m.travel_launch_pad()
					: role === 'origin'
						? m.travel_departure_mode()
						: m.travel_arrival_mode()}
			</span>
		</div>

		<ScrollArea
			class={fullscreen ? 'min-h-0 flex-1' : ''}
			viewportClasses={fullscreen ? 'h-full' : 'max-h-[26rem]'}
		>
			<div class="flex flex-col gap-2 pe-2">
				{#if showPads}
					<!-- Busiest first — the launch tally shows a range's best-known pad. -->
					{#each pads as pad (pad.code)}
						{@const active = pad.code === padCode}
						<button
							type="button"
							onclick={() => {
								onPadPick?.(pad);
								onOpenChange(false);
							}}
							aria-pressed={active}
							class="hover:bg-muted flex flex-col gap-0.5 rounded-md px-2 py-1.5 text-start {active
								? 'bg-muted'
								: ''}"
						>
							<span class="flex w-full items-baseline gap-2">
								<span class="flex-1 truncate text-xs font-medium">{pad.name}</span>
								{#if pad.launches > 0}
									<span class="text-muted-foreground shrink-0 text-[10px] tabular-nums">
										{m.tooltip_launches_count({ count: pad.launches })}
									</span>
								{/if}
							</span>
							{#if padPlaces > 1}
								<span class="text-muted-foreground block truncate text-[10px]">
									{pad.siteName}
								</span>
							{/if}
						</button>
					{/each}
				{/if}
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
										{endpointModeLabel(choice.kind, role)}
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
										<span>·</span>
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
										aria-valuetext={formatKm(customAltShown)}
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
{/snippet}

{#if fullscreen}
	<button type="button" class={TRIGGER} onclick={() => onOpenChange(true)}>
		{@render triggerBody()}
	</button>
	{#if open}
		<!-- Titled by the end it moves, not by the step: step two is reached from
		     inside and carries its own header. -->
		<FullscreenPicker
			title={role === 'origin' ? m.travel_from() : m.travel_to()}
			onClose={() => onOpenChange(false)}
		>
			{@render panel()}
		</FullscreenPicker>
	{/if}
{:else}
	<Popover.Root {open} onOpenChange={(next: boolean) => onOpenChange(next)}>
		<Popover.Trigger class="{TRIGGER} data-[state=open]:bg-background">
			{@render triggerBody()}
		</Popover.Trigger>
		<Popover.Content
			align="start"
			sideOffset={6}
			class="w-[20rem] max-w-[calc(100vw-2rem)] gap-0 p-2"
		>
			{@render panel()}
		</Popover.Content>
	</Popover.Root>
{/if}
