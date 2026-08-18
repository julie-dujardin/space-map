<!--
  Map chrome rather than a panel setting, because what it changes is the
  picture. On its face rather than behind a menu, because it is which of two
  pictures you are looking at, not a setting you set once.
-->
<script lang="ts" generics="T">
	import type { PillOption } from './pill-option';

	interface Props {
		/** Names the group, and leads the segments inside the same pill. */
		label: string;
		/** A word or two standing in for `label` on a phone, where the full phrase
		 *  is wider than the control it names. Omitted, the phone shows none. */
		shortLabel?: string;
		options: PillOption<T>[];
		value: T;
		onSelect: (value: T) => void;
	}
	let { label, shortLabel, options, value, onSelect }: Props = $props();
</script>

<!-- Below md the label shrinks to `shortLabel`, and off the narrowest phones
     goes entirely: the two options carry themselves, a clipped phrase doesn't. -->
<div class="pointer-events-auto inline-flex items-center rounded-full bg-black/40 backdrop-blur-md">
	{#if shortLabel}
		<span
			class="hidden truncate ps-3.5 pe-3 text-xs text-white/60 min-[360px]:inline md:hidden"
			aria-hidden="true"
		>
			{shortLabel}
		</span>
	{/if}
	<span class="hidden truncate ps-3.5 pe-3 text-xs text-white/60 md:inline" aria-hidden="true">
		{label}
	</span>
	<span
		class="hidden h-4 w-px bg-white/15 md:inline-block {shortLabel
			? 'min-[360px]:inline-block'
			: ''}"
	></span>
	<!-- Named by the group rather than by the visible label, so a screen reader
	     hears it once. No glass of its own: it is already on the pill's. -->
	<div class="inline-flex items-center gap-0.5 rounded-full p-0.5" role="group" aria-label={label}>
		{#each options as option (option.value)}
			{@const active = option.value === value}
			<button
				type="button"
				aria-pressed={active}
				title={option.description}
				onclick={() => onSelect(option.value)}
				class="flex cursor-pointer items-center gap-1.5 rounded-full px-3 py-1.5 text-xs transition-colors
					{active ? 'bg-white font-medium text-black' : 'text-white/70 hover:text-white'}"
			>
				<option.Icon class="size-3.5" />
				{option.label}
			</button>
		{/each}
	</div>
</div>
