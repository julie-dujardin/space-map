<!-- A search field with its clear button. -->
<script lang="ts">
	import type { HTMLInputAttributes } from 'svelte/elements';
	import SearchIcon from '@lucide/svelte/icons/search';
	import XIcon from '@lucide/svelte/icons/x';
	import * as m from '$lib/paraglide/messages.js';

	interface Props extends Omit<HTMLInputAttributes, 'value'> {
		value: string;
		input?: HTMLInputElement | null;
		/** Accessible name. */
		label: string;
	}
	let {
		value = $bindable(),
		input = $bindable(null),
		label,
		class: className = '',
		...rest
	}: Props = $props();
</script>

<div
	class="border-border/60 bg-background flex shrink-0 items-center gap-2 rounded-md border px-2 py-1.5 {className}"
>
	<SearchIcon class="text-muted-foreground size-3.5 shrink-0" />
	<!-- Deliberately not type="search": its native cancel button is drawn far heavier than the rest. -->
	<input
		bind:this={input}
		bind:value
		type="text"
		placeholder={m.travel_search_placeholder()}
		aria-label={label}
		autocomplete="off"
		spellcheck="false"
		class="placeholder:text-muted-foreground min-w-0 flex-1 bg-transparent text-sm outline-none"
		{...rest}
	/>
	{#if value}
		<button
			type="button"
			onclick={() => {
				value = '';
				input?.focus();
			}}
			aria-label={m.search_clear_search()}
			class="text-muted-foreground hover:bg-accent hover:text-foreground shrink-0 rounded-full p-0.5 transition-colors"
		>
			<XIcon class="size-3.5" />
		</button>
	{/if}
</div>
