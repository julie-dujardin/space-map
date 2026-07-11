<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import { getLocale, getTextDirection } from '$lib/paraglide/runtime.js';
	import * as Popover from '$lib/components/ui/popover';
	import CompassIcon from '@lucide/svelte/icons/compass';
	import EarthIcon from '@lucide/svelte/icons/earth';
	import OrbitIcon from '@lucide/svelte/icons/orbit';
	import SparklesIcon from '@lucide/svelte/icons/sparkles';
	import { GALACTIC_REF_ID, type NorthChoice } from '$lib/scene/camera/north-reference';

	interface Props {
		choices: NorthChoice[];
		selectedId: string | null;
		onSelect: (id: string | null) => void;
	}

	let { choices, selectedId, onSelect }: Props = $props();
	let open = $state(false);

	// The control sits at the inline-end edge; open the popover toward screen centre.
	const side = $derived(getTextDirection(getLocale()) === 'rtl' ? 'right' : 'left');
</script>

<Popover.Root bind:open>
	<Popover.Trigger
		class="pointer-events-auto relative flex items-center justify-center
			w-10 h-10 md:w-8 md:h-8 rounded-full
			bg-black/40 backdrop-blur-md hover:bg-black/55
			text-white transition-colors cursor-pointer"
		title={m.north_reference()}
		aria-label={m.north_reference()}
	>
		<CompassIcon class="size-5 md:size-4" />
		<span
			class="absolute -bottom-0.5 -end-0.5 size-5 md:size-4.5 rounded-full
				bg-white text-black
				flex items-center justify-center pointer-events-none"
			aria-hidden="true"
		>
			{#if selectedId === null}
				<OrbitIcon class="size-3.5" />
			{:else if selectedId === GALACTIC_REF_ID}
				<SparklesIcon class="size-3.5" />
			{:else}
				<EarthIcon class="size-3.5" />
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
							onSelect(choice.id);
							open = false;
						}}
					>
						<div class="text-sm">
							{#if choice.id === null}
								{m.north_solar_system()}
							{:else if choice.id === GALACTIC_REF_ID}
								{m.north_galactic()}
							{:else}
								{choice.name ?? choice.id}
							{/if}
						</div>
						<div class="text-xs text-muted-foreground">
							{#if choice.id === null}
								{m.north_solar_system_desc()}
							{:else if choice.id === GALACTIC_REF_ID}
								{m.north_galactic_desc()}
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
