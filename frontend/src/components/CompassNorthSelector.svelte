<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import { getLocale, getTextDirection } from '$lib/paraglide/runtime.js';
	import * as Popover from '$lib/components/ui/popover';
	import EarthIcon from '@lucide/svelte/icons/earth';
	import OrbitIcon from '@lucide/svelte/icons/orbit';
	import SatelliteIcon from '@lucide/svelte/icons/satellite';
	import SparklesIcon from '@lucide/svelte/icons/sparkles';
	import type { NorthChoice } from '$lib/scene/camera/north-reference';
	import { GALACTIC_REF_ID } from '$lib/state/north';

	interface Props {
		choices: NorthChoice[];
		selectedId: string | null;
		/** The view's heading off north, in radians, counterclockwise as seen
		 *  from above: the needle turns clockwise by it. */
		heading: number;
		onSelect: (choice: NorthChoice) => void;
		onResetNorth: () => void;
	}

	let { choices, selectedId, heading, onSelect, onResetNorth }: Props = $props();
	const selected = $derived(choices.find((c) => c.id === selectedId));
	let open = $state(false);

	// The control sits at the inline-end edge; open the popover toward screen centre.
	const side = $derived(getTextDirection(getLocale()) === 'rtl' ? 'right' : 'left');

	/** Longest gap between two taps of a double tap, in ms. Touch browsers do
	 *  not all send dblclick, so taps are timed here. */
	const DOUBLE_TAP_MS = 350;
	let lastTap = -Infinity;
	/** Whether the press being clicked was a touch: a double tap opens the
	 *  menu there, a right click does with a mouse. */
	let touched = false;

	function onpointerdown(event: PointerEvent) {
		touched = event.pointerType !== 'mouse';
	}

	// Each tap resets at once, so a double tap resets and opens the menu,
	// whose choices turn the view to their north anyway.
	function onclick(event: MouseEvent) {
		event.preventDefault();
		if (open) {
			open = false;
			return;
		}
		if (touched && event.timeStamp - lastTap < DOUBLE_TAP_MS) {
			lastTap = -Infinity;
			open = true;
			return;
		}
		lastTap = event.timeStamp;
		onResetNorth();
	}

	function oncontextmenu(event: MouseEvent) {
		event.preventDefault();
		open = true;
	}

	function onkeydown(event: KeyboardEvent) {
		if (event.key === 'Enter' || event.key === ' ') {
			event.preventDefault();
			onResetNorth();
		} else if (event.key === 'ArrowDown') {
			event.preventDefault();
			open = true;
		}
	}
</script>

<Popover.Root bind:open>
	<Popover.Trigger
		class="relative flex items-center justify-center
			w-10 h-10 md:w-8 md:h-8 rounded-full
			bg-black/40 backdrop-blur-md hover:bg-black/55
			text-white transition-colors cursor-pointer touch-manipulation"
		title={m.north_compass()}
		aria-label={m.north_compass()}
		{onpointerdown}
		{onclick}
		{oncontextmenu}
		{onkeydown}
	>
		<svg
			viewBox="0 0 24 24"
			class="size-6 md:size-5"
			style:transform="rotate({heading}rad)"
			aria-hidden="true"
		>
			<path d="M12 2.5 L15.5 12 H8.5 Z" class="fill-red-500" />
			<path
				d="M8.5 12 H15.5 L12 21.5 Z"
				class="fill-white/15 stroke-white"
				stroke-width="1.25"
				stroke-linejoin="round"
			/>
		</svg>
		<span
			class="absolute -bottom-1 -end-1 size-4 md:size-3.5 rounded-full
				bg-white text-black
				flex items-center justify-center pointer-events-none"
			aria-hidden="true"
		>
			{#if selectedId === null || selected?.plane}
				<OrbitIcon class="size-3 md:size-2.5" />
			{:else if selectedId === GALACTIC_REF_ID}
				<SparklesIcon class="size-3 md:size-2.5" />
			{:else if selected?.probe}
				<SatelliteIcon class="size-3 md:size-2.5" />
			{:else}
				<EarthIcon class="size-3 md:size-2.5" />
			{/if}
		</span>
	</Popover.Trigger>
	<Popover.Content {side} align="end" sideOffset={8} class="w-48 p-1">
		<div class="px-3 pt-2 pb-1 text-xs font-medium text-muted-foreground">
			{m.north_reference()}
		</div>
		<ul class="flex flex-col">
			{#each choices as choice (choice.id ?? 'solar-system')}
				{@const active = choice.id === selectedId}
				<li>
					<button
						type="button"
						class="w-full text-start px-3 py-2 rounded cursor-pointer
							hover:bg-accent hover:text-accent-foreground transition-colors
							{active ? 'bg-accent text-accent-foreground font-medium' : ''}"
						onclick={() => {
							onSelect(choice);
							open = false;
						}}
					>
						<div class="text-sm">
							{#if choice.id === null}
								{m.north_solar_system()}
							{:else if choice.id === GALACTIC_REF_ID}
								{m.north_galactic()}
							{:else if choice.plane}
								{m.planetary_system_title({ primary: choice.name ?? '' })}
							{:else}
								{choice.name ?? choice.id}
							{/if}
						</div>
						<div class="text-xs text-muted-foreground">
							{#if choice.id === null}
								{m.north_solar_system_desc()}
							{:else if choice.id === GALACTIC_REF_ID}
								{m.north_galactic_desc()}
							{:else if choice.plane}
								{m.north_system_desc()}
							{:else if choice.probe}
								{m.north_probe_desc()}
							{:else}
								{m.north_body_desc()}
							{/if}
						</div>
					</button>
				</li>
			{/each}
		</ul>
	</Popover.Content>
</Popover.Root>
