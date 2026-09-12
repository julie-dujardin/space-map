<script lang="ts">
	import { getContext } from 'svelte';
	import type { AppState } from '$lib/state/app-state.svelte';
	import { groupClick, groupHref } from '$lib/state/focus-link';
	import { formatCompactNumber } from '$lib/format/quantities';

	interface Props {
		slug: string;
		name: string;
		n?: number;
		/** Highlights the chip for the focused group. */
		active?: boolean;
	}
	let { slug, name, n = 0, active = false }: Props = $props();

	const appState = getContext<AppState | undefined>('appState');

	let href = $derived(groupHref(appState, slug, name));
	let onClick = $derived(groupClick(appState, slug, name));
</script>

<a
	{href}
	onclick={onClick}
	aria-current={active ? 'page' : undefined}
	class="flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs transition-colors {active
		? 'border-foreground/40 bg-muted/60'
		: 'border-border/60 hover:bg-muted/60'}"
>
	<span class="font-medium">{name}</span>
	{#if n > 0}
		<span class="text-muted-foreground tabular-nums">{formatCompactNumber(n)}</span>
	{/if}
</a>
