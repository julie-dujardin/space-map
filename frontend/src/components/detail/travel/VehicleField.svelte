<!--
  The craft box: closed it names what you are flying, open it is a popover over
  the catalogue with a search bar.

  Same shape as the endpoint boxes above it, for the same reason — the catalogue
  runs to dozens of craft and a scrolling list of them was pushing the
  trajectories off the panel. The search filters what the trip could be flown
  with, not the whole catalogue: a craft that cannot leave this way is already
  gone before anything is typed.
-->
<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import CheckIcon from '@lucide/svelte/icons/check';
	import ChevronDownIcon from '@lucide/svelte/icons/chevron-down';
	import RocketIcon from '@lucide/svelte/icons/rocket';
	import SearchIcon from '@lucide/svelte/icons/search';
	import UsersIcon from '@lucide/svelte/icons/users';
	import XIcon from '@lucide/svelte/icons/x';
	import * as Popover from '$lib/components/ui/popover/index.js';
	import { ScrollArea } from '$lib/components/ui/scroll-area/index.js';
	import {
		canDepartFrom,
		crewCapacity,
		type DepartureMode,
		type Manifest,
		type Route,
		type Vehicle
	} from '$lib/math/travel';
	import { departureNote, vehicleDescription, vehicleName } from './vehicle-labels';
	import VehicleMeta from './VehicleMeta.svelte';

	interface Props {
		/** Craft the trip could be flown with, already filtered by the panel. */
		vehicles: readonly Vehicle[];
		/** Whether the catalogue has landed — tells "still loading" from "none fit". */
		loaded: boolean;
		selected: Vehicle | null;
		/** The trajectory being read, so each row can price itself against it. */
		route: Route | null;
		manifest: Manifest;
		/** Seats only matter once someone is aboard. */
		passengers: number;
		departureMode: DepartureMode;
		onSelect: (id: string) => void;
		open: boolean;
		onOpenChange: (open: boolean) => void;
	}
	let {
		vehicles,
		loaded,
		selected,
		route,
		manifest,
		passengers,
		departureMode,
		onSelect,
		open,
		onOpenChange
	}: Props = $props();

	let query = $state('');
	let input = $state<HTMLInputElement | null>(null);
	let list = $state<HTMLElement | null>(null);

	// The catalogue is alphabetical and long, so a craft chosen from the bottom of
	// it would open the list nowhere near itself.
	$effect(() => {
		list?.querySelector('[aria-pressed="true"]')?.scrollIntoView({ block: 'nearest' });
	});

	// Each opening is its own question: a filter left over from the last one would
	// hide craft nobody asked to hide.
	$effect(() => {
		if (!open) query = '';
	});
	$effect(() => {
		if (open) input?.focus();
	});

	/** Accent-blind, so a French locale's names match an ASCII keyboard. */
	function fold(text: string): string {
		return text
			.normalize('NFD')
			.replace(/\p{Diacritic}/gu, '')
			.toLowerCase();
	}

	// The description too: half the catalogue is named in a language or a series
	// the reader may not know, and "lunar lander" finds those.
	function haystack(vehicle: Vehicle): string {
		return fold(`${vehicleName(vehicle)} ${vehicleDescription(vehicle) ?? ''}`);
	}

	let shown = $derived.by(() => {
		const q = fold(query.trim());
		if (!q) return vehicles;
		return vehicles.filter((vehicle) => haystack(vehicle).includes(q));
	});

	function choose(vehicle: Vehicle) {
		onSelect(vehicle.id);
		onOpenChange(false);
	}
</script>

<Popover.Root {open} onOpenChange={(next: boolean) => onOpenChange(next)}>
	<Popover.Trigger
		class="border-border/60 bg-muted/40 hover:bg-muted data-[state=open]:bg-background flex w-full items-center gap-2 rounded-md border px-2.5 py-2 text-start transition-colors"
	>
		<RocketIcon class="text-muted-foreground size-4 shrink-0" />
		<span class="min-w-0 flex-1">
			<span class="block truncate text-sm {selected ? '' : 'text-muted-foreground'}">
				{selected ? vehicleName(selected) : m.travel_add_craft()}
			</span>
			{#if selected}
				<VehicleMeta vehicle={selected} {route} {manifest} />
			{/if}
		</span>
		<ChevronDownIcon class="text-muted-foreground size-4 shrink-0" />
	</Popover.Trigger>

	<Popover.Content align="start" sideOffset={6} class="w-[22rem] gap-0 p-2">
		<div
			class="border-border/60 bg-background mb-2 flex items-center gap-2 rounded-md border px-2 py-1.5"
		>
			<SearchIcon class="text-muted-foreground size-3.5 shrink-0" />
			<!-- Deliberately not type="search": its native cancel button is drawn far
			     heavier than the rest of the panel. -->
			<input
				bind:this={input}
				bind:value={query}
				type="text"
				placeholder={m.travel_search_placeholder()}
				aria-label={m.travel_search_placeholder()}
				autocomplete="off"
				spellcheck="false"
				class="placeholder:text-muted-foreground min-w-0 flex-1 bg-transparent text-sm outline-none"
			/>
			{#if query}
				<button
					type="button"
					onclick={() => {
						query = '';
						input?.focus();
					}}
					aria-label={m.search_clear_search()}
					class="text-muted-foreground hover:bg-accent hover:text-foreground shrink-0 rounded-full p-0.5 transition-colors"
				>
					<XIcon class="size-3.5" />
				</button>
			{/if}
		</div>

		{#if shown.length > 0}
			<ScrollArea viewportClasses="max-h-[26rem]">
				<ul bind:this={list} class="flex flex-col pe-2">
					{#each shown as vehicle (vehicle.id)}
						<!-- Only the chosen craft survives the panel's filter without fitting
						     the departure, so the note reads as "here is why it stopped
						     working", not as a rule on the list. -->
						{@const fits = canDepartFrom(vehicle, departureMode)}
						{@const seats = passengers > 0 ? crewCapacity(vehicle) : null}
						{@const tooSmall = seats !== null && seats < passengers}
						{@const active = selected?.id === vehicle.id}
						<li>
							<button
								type="button"
								onclick={() => choose(vehicle)}
								aria-pressed={active}
								class="hover:bg-muted flex w-full items-start gap-2 rounded-md px-2 py-1.5 text-start text-xs {active
									? 'bg-muted'
									: ''} {tooSmall ? 'opacity-50' : ''}"
							>
								<span class="min-w-0 flex-1">
									<span class="flex items-center gap-2">
										<span
											class="min-w-0 flex-1 truncate font-medium {fits
												? ''
												: 'text-muted-foreground'}"
										>
											{vehicleName(vehicle)}
										</span>
										{#if !fits}
											<span class="text-muted-foreground shrink-0 text-[11px]">
												{departureNote(vehicle)}
											</span>
										{/if}
										{#if seats !== null}
											<span
												class="text-muted-foreground flex shrink-0 items-center gap-1 tabular-nums"
												title={m.travel_seats({ value: seats })}
											>
												<UsersIcon class="size-3" />{seats}
											</span>
										{/if}
										{#if active}
											<CheckIcon class="size-3.5 shrink-0" />
										{/if}
									</span>
									<VehicleMeta {vehicle} {route} {manifest} />
								</span>
							</button>
						</li>
					{/each}
				</ul>
			</ScrollArea>
		{:else if !loaded}
			<p class="text-muted-foreground px-2 py-1 text-xs">{m.travel_craft_loading()}</p>
		{:else if query.trim()}
			<p class="text-muted-foreground px-2 py-1 text-xs">{m.travel_search_empty()}</p>
		{:else}
			<p class="text-muted-foreground px-2 py-1 text-xs">{m.travel_no_craft_for_route()}</p>
		{/if}
	</Popover.Content>
</Popover.Root>
