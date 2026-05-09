<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import * as Popover from '$lib/components/ui/popover';
	import CompassIcon from '@lucide/svelte/icons/compass';
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
		class="pointer-events-auto flex items-center justify-center
			w-12 h-12 md:w-10 md:h-10 rounded-full
			bg-primary-foreground hover:bg-primary-foreground/80
			text-primary transition-colors cursor-pointer"
		title={m.north_reference()}
		aria-label={m.north_reference()}
	>
		<CompassIcon class="size-7 md:size-5" />
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
						class="w-full text-start px-3 py-2 rounded text-sm cursor-pointer
							hover:bg-accent hover:text-accent-foreground transition-colors
							{active ? 'bg-accent text-accent-foreground font-medium' : ''}"
						onclick={() => {
							onSelect(choice.id);
							open = false;
						}}
					>
						{choice.id === null ? m.north_solar_system() : (choice.name ?? choice.id)}
					</button>
				</li>
			{/each}
		</ul>
	</Popover.Content>
</Popover.Root>
