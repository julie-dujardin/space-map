<script module lang="ts">
	export interface Attribution {
		license?: string;
		license_url?: string;
		artist?: string;
		description?: string;
		/** ISO-truncated creation date from Commons (P571 / DateTimeOriginal). */
		date?: string;
	}
</script>

<script lang="ts">
	import MinusIcon from '@lucide/svelte/icons/minus';
	import PlusIcon from '@lucide/svelte/icons/plus';
	import ExternalLinkIcon from '@lucide/svelte/icons/external-link';
	import { ScrollArea } from '$lib/components/ui/scroll-area/index.js';
	import * as m from '$lib/paraglide/messages.js';
	import { formatIsoDate } from '$lib/format/date';
	import type { ObjectImage } from '$lib/fetch/objects/object-data';

	interface Props {
		image: ObjectImage | null;
		attribution: Attribution | null;
	}

	let { image, attribution }: Props = $props();

	let expanded = $state(false);
	let viewportRef = $state<HTMLElement | null>(null);
	let truncated = $state(false);

	// Reset on slide change. The bare `image;` is a dependency read — Svelte
	// tracks property accesses inside an effect, so reading it here is what
	// makes the effect re-run when the slide changes. ESLint can't see that
	// intent, hence the disable.
	$effect(() => {
		// eslint-disable-next-line @typescript-eslint/no-unused-expressions
		image;
		expanded = false;
	});

	const paragraphs = $derived(
		attribution?.description ? attribution.description.split('\n').filter((p) => p.trim()) : []
	);
	const hasExplicitBreaks = $derived((attribution?.description ?? '').includes('\n'));

	// Re-measure overflow whenever the viewport's content or size changes.
	// The viewport's max-height stays constant when paragraphs grow, so
	// ResizeObserver alone wouldn't fire — we explicitly read paragraphs/
	// hasExplicitBreaks as dependencies to force the effect to re-run.
	// ESLint flags those bare reads as unused; disabled because the read
	// itself is the side effect (Svelte dep tracking).
	$effect(() => {
		// eslint-disable-next-line @typescript-eslint/no-unused-expressions
		paragraphs;
		// eslint-disable-next-line @typescript-eslint/no-unused-expressions
		hasExplicitBreaks;
		const el = viewportRef;
		if (!el) {
			truncated = false;
			return;
		}
		const measure = () => {
			truncated = el.scrollHeight > el.clientHeight + 1 || hasExplicitBreaks;
		};
		const ro = new ResizeObserver(measure);
		ro.observe(el);
		measure();
		return () => ro.disconnect();
	});
</script>

{#if paragraphs.length}
	<div class="pswp-sm-caption-desc-wrap" class:is-expanded={expanded}>
		<ScrollArea class="pswp-sm-caption-scroll {expanded ? 'is-expanded' : ''}" bind:viewportRef>
			<div class="pswp-sm-caption-desc">
				{#each paragraphs as p, i (i)}
					<p>{p}</p>
				{/each}
			</div>
		</ScrollArea>
		{#if truncated}
			<button
				type="button"
				class="pswp-sm-caption-toggle"
				onclick={(e) => {
					e.stopPropagation();
					expanded = !expanded;
				}}
			>
				{expanded ? m.show_less() : m.read_more()}
				{#if expanded}
					<MinusIcon class="size-3.5" />
				{:else}
					<PlusIcon class="size-3.5" />
				{/if}
			</button>
		{/if}
	</div>
{/if}

{#if image}
	<div class="pswp-sm-caption-credits">
		{#if attribution?.license}
			{#if attribution.license_url}
				<a
					href={attribution.license_url}
					target="_blank"
					rel="noopener noreferrer license"
					class="inline-flex items-center gap-1"
					>{attribution.license}<ExternalLinkIcon class="size-3 shrink-0" /></a
				>
			{:else}
				{attribution.license}
			{/if}
			<span class="pswp-sm-caption-sep" aria-hidden="true">·</span>
		{/if}
		{#if attribution?.artist}
			<span class="pswp-sm-caption-artist">{attribution.artist}</span>
			<span class="pswp-sm-caption-sep" aria-hidden="true">·</span>
		{/if}
		{#if attribution?.date}
			<span class="pswp-sm-caption-date">{formatIsoDate(attribution.date)}</span>
			<span class="pswp-sm-caption-sep" aria-hidden="true">·</span>
		{/if}
		<a
			href={image.source_url}
			target="_blank"
			rel="noopener noreferrer"
			class="inline-flex items-center gap-1"
			>{m.image_view_on_commons()}<ExternalLinkIcon class="size-3 shrink-0" /></a
		>
	</div>
{/if}
