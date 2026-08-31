<!--
  One list row: thumbnail (or letter tile) + name + a stacked right-hand
  column supplied by the caller. Shared by the member lists and the probe
  target list so the row look lives in one place.
-->
<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { HTMLAttributes } from 'svelte/elements';
	import { pickedThumbnailUrl, type PickedThumbnail } from '$lib/fetch/objects/images';

	interface Props extends HTMLAttributes<HTMLElement> {
		name: string;
		thumbnail?: PickedThumbnail;
		href?: string;
		onclick?: (e: MouseEvent) => void;
		/** Extra classes on the right-hand column (e.g. tabular-nums). */
		valuesClass?: string;
		/** Wrap the right-hand column onto further lines instead of stacking it
		 *  on one: a probe's list of targets is a sentence, not a pair of figures. */
		valuesWrap?: boolean;
		/** The right-hand column's stacked values. */
		children?: Snippet;
	}
	let {
		name,
		thumbnail,
		href,
		onclick,
		valuesClass = '',
		valuesWrap = false,
		children,
		...rest
	}: Props = $props();
</script>

{#snippet content()}
	{#if thumbnail}
		<img
			src={pickedThumbnailUrl(thumbnail)}
			alt=""
			loading="lazy"
			decoding="async"
			class="bg-muted size-10 shrink-0 rounded-md object-cover"
		/>
	{:else}
		<div
			class="bg-muted text-muted-foreground flex size-10 shrink-0 items-center justify-center rounded-md text-sm font-medium"
		>
			{name.charAt(0)}
		</div>
	{/if}
	<span class="min-w-0 flex-1 truncate text-sm font-medium">{name}</span>
	{#if children}
		<span
			class="flex text-xs {valuesWrap
				? 'min-w-0 max-w-[70%] flex-wrap justify-end gap-x-3'
				: 'shrink-0 flex-col items-end'} {valuesClass}"
		>
			{@render children()}
		</span>
	{/if}
{/snippet}

<li>
	{#if href !== undefined || onclick !== undefined}
		<a
			{href}
			{onclick}
			class="pointer-events-auto hover:bg-muted/40 -mx-1 flex items-center gap-3 rounded-md px-1 py-2"
			{...rest}
		>
			{@render content()}
		</a>
	{:else}
		<div class="-mx-1 flex items-center gap-3 px-1 py-2">
			{@render content()}
		</div>
	{/if}
</li>
