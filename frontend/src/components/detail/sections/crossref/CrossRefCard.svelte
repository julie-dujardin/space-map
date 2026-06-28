<script lang="ts">
	import type { Snippet } from 'svelte';

	interface Props {
		href?: string;
		onclick?: (e: MouseEvent) => void;
		/** Full name — shown as the tile title (the display text may be truncated). */
		title?: string;
		/** Hero image URL, or a promise resolving to one (fetched lazily). */
		hero?: string | Promise<string | undefined>;
		/** Custom background (e.g. a diagram), rendered instead of the hero image. */
		background?: Snippet;
		/** Compact text shown on the tile. */
		display: string;
		label: string;
		/** Extra classes — e.g. `col-span-2` to span a full grid row. */
		class?: string;
	}
	let {
		href,
		onclick,
		title,
		hero,
		background,
		display,
		label,
		class: className
	}: Props = $props();
</script>

<a
	{href}
	{onclick}
	{title}
	class="border-border/60 bg-muted pointer-events-auto relative block h-20 overflow-hidden rounded-md border {className}"
>
	{#if background}
		<div class="absolute inset-0">{@render background()}</div>
	{:else}
		{#await Promise.resolve(hero) then src}
			{#if src}
				<img
					{src}
					alt=""
					loading="lazy"
					decoding="async"
					class="absolute inset-0 size-full object-cover"
				/>
			{/if}
		{/await}
	{/if}
	<div class="absolute inset-0 bg-gradient-to-t from-black/85 via-black/30 to-transparent"></div>
	<div class="absolute inset-x-0 bottom-0 flex flex-col gap-0.5 p-2.5">
		<span class="truncate text-sm font-semibold text-white">{display}</span>
		<span class="truncate text-[10px] uppercase text-white/70">{label}</span>
	</div>
</a>
