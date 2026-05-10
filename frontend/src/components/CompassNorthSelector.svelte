<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import * as Popover from '$lib/components/ui/popover';
	import CompassIcon from '@lucide/svelte/icons/compass';
	import EarthIcon from '@lucide/svelte/icons/earth';
	import OrbitIcon from '@lucide/svelte/icons/orbit';
	import type { NorthChoice } from '$lib/scene/north-reference';

	interface Props {
		choices: NorthChoice[];
		selectedId: string | null;
		onSelect: (id: string | null) => void;
	}

	let { choices, selectedId, onSelect }: Props = $props();
	let open = $state(false);
</script>

<Popover.Root bind:open>
	<Popover.Trigger
		class="pointer-events-auto relative flex items-center justify-center
			w-10 h-10 md:w-8 md:h-8 rounded-full
			bg-primary-foreground hover:bg-primary-foreground/80
			text-primary transition-colors cursor-pointer"
		title={m.north_reference()}
		aria-label={m.north_reference()}
	>
		<CompassIcon class="size-5 md:size-4" />
		<span
			class="absolute -bottom-0.5 -end-0.5 size-5 md:size-4.5 rounded-full
				bg-primary text-primary-foreground
				flex items-center justify-center pointer-events-none"
			aria-hidden="true"
		>
			{#if selectedId === null}
				<OrbitIcon class="size-3.5" />
			{:else}
				<EarthIcon class="size-3.5" />
			{/if}
		</span>
	</Popover.Trigger>
	<Popover.Content side="left" align="end" sideOffset={8} class="w-48 p-1">
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
							{choice.id === null ? m.north_solar_system() : (choice.name ?? choice.id)}
						</div>
						<div class="text-xs text-muted-foreground">
							{choice.id === null ? m.north_solar_system_desc() : m.north_body_desc()}
						</div>
					</button>
				</li>
			{/each}
		</ul>
	</Popover.Content>
</Popover.Root>
