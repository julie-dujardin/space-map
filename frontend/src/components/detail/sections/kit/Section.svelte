<script lang="ts">
	import type { Snippet } from 'svelte';
	import ArrowRightIcon from '@lucide/svelte/icons/arrow-right';

	interface Props {
		title: string;
		/** Optional: a section can be all chart and no label/value pairs. */
		children?: Snippet;
		header?: Snippet;
		/** Full-width content after the rows — for anything that isn't a label/value pair. */
		footer?: Snippet;
		/** A qualifier on the whole section, set opposite the title. The
		 *  cross-sections use it to say what they are drawn to scale against. */
		meta?: string;
		/** Where the section continues, if it does. Set opposite the title, the
		 *  way the member strips carry "See all" — a row of its own under the
		 *  values read as another datum. */
		activateHref?: string;
		/** Takes the plain left-click in-session; the href covers the rest. */
		onActivate?: (e: MouseEvent) => void;
		/** What following it leads to. */
		activateLabel?: string;
		/** Makes the title itself lead where `activateHref` does, for sections
		 *  whose heading names a destination rather than the rows below it. */
		titleHref?: string;
		/** A qualifier on the title itself, set right after it — how many things
		 *  the heading names. Unlike `meta`, which the row's spacing pushes to
		 *  wherever the title happens to end, this stays attached to the words. */
		titleMeta?: string;
	}

	let {
		title,
		children,
		header,
		footer,
		meta,
		activateHref,
		onActivate,
		activateLabel,
		titleHref,
		titleMeta
	}: Props = $props();
</script>

{#snippet titleCount()}
	<span class="text-muted-foreground shrink-0 text-xs font-normal tabular-nums">{titleMeta}</span>
{/snippet}

<div class="flex flex-col gap-1">
	<div class="flex items-baseline justify-between gap-3">
		<h3 class="min-w-0 text-sm font-medium">
			{#if titleHref}
				<a
					href={titleHref}
					onclick={onActivate}
					class="flex min-w-0 items-baseline gap-2 hover:underline"
				>
					<span class="truncate">{title}</span>
					{#if titleMeta}{@render titleCount()}{/if}
				</a>
			{:else}
				<span class="flex min-w-0 items-baseline gap-2">
					<span class="truncate">{title}</span>
					{#if titleMeta}{@render titleCount()}{/if}
				</span>
			{/if}
		</h3>
		{#if meta}
			<span class="text-muted-foreground shrink-0 text-[10px] tabular-nums">{meta}</span>
		{/if}
		{#if activateHref}
			<!-- The section is named again, silently, after the label: on its own
			     "See layers" is one of several identical links down the panel to
			     anyone listening to them rather than reading them. It follows the
			     visible text rather than replacing it, which an aria-label would. -->
			<a
				href={activateHref}
				onclick={onActivate}
				class="text-muted-foreground hover:text-foreground inline-flex shrink-0 items-center gap-1 text-xs"
			>
				{activateLabel}
				<span class="sr-only">— {title}</span>
				<ArrowRightIcon class="size-3 rtl:rotate-180" />
			</a>
		{/if}
	</div>
	<div class="border-border/60 border-t"></div>
	{#if header}{@render header()}{/if}
	{#if children}
		<dl class="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2.5 text-sm">
			{@render children()}
		</dl>
	{/if}
	{#if footer}
		<div class="mt-2.5 flex flex-col gap-3">{@render footer()}</div>
	{/if}
</div>
