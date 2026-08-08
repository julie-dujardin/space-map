<!--
  An endpoint box: closed it summarises where you start or arrive and how; open
  it is where both are chosen.

  Open, it reads top to bottom in the order the questions actually arise —
  *where* first, from the catalogue search, and only then *how*, because how you
  arrive is a question about somewhere. A surface feature answers both at once:
  there is no way to reach a named crater except by landing in it, so its box
  has no mode row at all.
-->
<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import ChevronDownIcon from '@lucide/svelte/icons/chevron-down';
	import MapPinIcon from '@lucide/svelte/icons/map-pin';
	import { ORIGIN_MODES, TARGET_MODES, type EndpointMode } from '$lib/travel/panel.svelte';
	import type { TravelEndpointPick } from '$lib/travel/endpoint';
	import Segmented from './Segmented.svelte';
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
		open: boolean;
		onToggle: () => void;
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
		open,
		onToggle,
		excludeIds,
		onPick
	}: Props = $props();

	const LABELS: Record<EndpointMode, () => string> = {
		surface: () => (role === 'origin' ? m.travel_mode_surface() : m.travel_mode_landing()),
		'low-orbit': () => (role === 'origin' ? m.travel_mode_orbit() : m.travel_mode_low_orbit()),
		elliptical: () => m.travel_mode_elliptical(),
		flyby: () => m.travel_mode_flyby()
	};

	// Only a destination can be orbited two ways or flown past; a departure is
	// from the ground or from a parking orbit.
	let allowed = $derived(role === 'origin' ? ORIGIN_MODES : TARGET_MODES);

	// The two orbits are one answer with a follow-up, not two peers of "landing"
	// — four abreast in a 390px column is unreadable.
	let isOrbit = $derived(mode === 'low-orbit' || mode === 'elliptical');
	let topLevel = $derived(
		allowed
			.filter((v) => v !== 'elliptical')
			.map((value) => ({ value, label: LABELS[value]() }))
			.map((o) =>
				o.value === 'low-orbit' && role === 'target' ? { ...o, label: m.travel_mode_orbit() } : o
			)
	);
	let orbitChoices = $derived([
		{ value: 'low-orbit' as const, label: m.travel_mode_low_orbit() },
		{ value: 'elliptical' as const, label: m.travel_mode_elliptical() }
	]);

	let modeLabel = $derived(LABELS[mode]());
	/** Landing is the only way to a named place, so the badge says nothing new. */
	let showMode = $derived(bodyName !== null && !isFeature);
</script>

<div
	class="border-border/60 overflow-hidden rounded-md border transition-colors {open
		? 'bg-background'
		: 'bg-muted/40'}"
>
	<button
		type="button"
		onclick={onToggle}
		aria-expanded={open}
		class="hover:bg-muted flex w-full items-center gap-2.5 px-2.5 py-2 text-start"
	>
		<!-- Both markers sit in the same box so the two fields' text lines up. -->
		<span class="flex size-3.5 shrink-0 items-center justify-center">
			{#if role === 'origin'}
				<span class="border-muted-foreground size-2 rounded-full border-2"></span>
			{:else}
				<MapPinIcon class="text-foreground size-3.5" />
			{/if}
		</span>
		<span class="min-w-0 flex-1">
			<span class="flex items-baseline gap-1.5">
				<span class="truncate text-sm font-medium {bodyName ? '' : 'text-muted-foreground'}">
					{bodyName ?? placeholder}
				</span>
				{#if showMode}
					<span
						class="border-border/60 text-muted-foreground shrink-0 rounded-sm border px-1 text-[10px] uppercase"
					>
						{modeLabel}
					</span>
				{/if}
			</span>
			<span class="text-muted-foreground block truncate text-xs">
				{role === 'origin' ? m.travel_from() : m.travel_to()}
			</span>
		</span>
		<ChevronDownIcon
			class="text-muted-foreground size-4 shrink-0 transition-transform {open ? 'rotate-180' : ''}"
		/>
	</button>

	{#if open}
		<div class="border-border/60 flex flex-col gap-2.5 border-t p-2.5">
			<EndpointSearch {excludeIds} {onPick} />

			{#if bodyName !== null && !isFeature}
				<div class="border-border/60 flex flex-col gap-2 border-t pt-2.5">
					<Segmented
						options={topLevel}
						value={isOrbit && role === 'target' ? 'low-orbit' : mode}
						onchange={onModeChange}
						ariaLabel={role === 'origin' ? m.travel_departure_mode() : m.travel_arrival_mode()}
						dense
					/>
					{#if role === 'target' && isOrbit}
						<Segmented
							options={orbitChoices}
							value={mode}
							onchange={onModeChange}
							ariaLabel={m.travel_orbit_shape()}
							dense
						/>
					{/if}
				</div>
			{/if}
		</div>
	{/if}
</div>
