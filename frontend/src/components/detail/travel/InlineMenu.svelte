<!--
  A choice written as the word it currently reads, with a chevron after it.

  Where a segmented control spends a full row showing every option at once,
  this spends a phrase: the timing mode and the aero assist share one line and
  the trajectories come up that much sooner.
-->
<script lang="ts" generics="T extends string">
	import ChevronDownIcon from '@lucide/svelte/icons/chevron-down';
	import * as Popover from '$lib/components/ui/popover/index.js';

	interface Props {
		options: readonly { value: T; label: string }[];
		value: T;
		onchange: (value: T) => void;
		ariaLabel: string;
		/** Which edge the menu hangs from, so a trailing control opens inwards. */
		align?: 'start' | 'end';
		/** Secondary choices read grey until opened, so one line carries one voice. */
		muted?: boolean;
	}
	let { options, value, onchange, ariaLabel, align = 'start', muted = false }: Props = $props();

	let open = $state(false);

	let current = $derived(options.find((option) => option.value === value));
</script>

<Popover.Root bind:open>
	<Popover.Trigger
		class="hover:text-foreground data-[state=open]:text-foreground flex shrink-0 items-center gap-1 text-xs transition-colors {muted
			? 'text-muted-foreground'
			: ''}"
		aria-label={ariaLabel}
	>
		{current?.label ?? ''}
		<ChevronDownIcon
			class="text-muted-foreground size-3.5 shrink-0 transition-transform {open
				? 'rotate-180'
				: ''}"
			aria-hidden="true"
		/>
	</Popover.Trigger>
	<Popover.Content {align} sideOffset={6} class="flex w-auto min-w-40 flex-col p-1">
		{#each options as option (option.value)}
			<button
				type="button"
				aria-pressed={option.value === value}
				onclick={() => {
					onchange(option.value);
					open = false;
				}}
				class="hover:bg-muted flex items-center gap-2 rounded-md px-2 py-1.5 text-start text-xs transition-colors {option.value ===
				value
					? 'text-foreground'
					: 'text-muted-foreground'}"
			>
				<span class="flex-1 whitespace-nowrap">{option.label}</span>
				{#if option.value === value}
					<span class="bg-foreground size-1.5 shrink-0 rounded-full" aria-hidden="true"></span>
				{/if}
			</button>
		{/each}
	</Popover.Content>
</Popover.Root>
