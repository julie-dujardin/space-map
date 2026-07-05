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
	import { safeHttpUrl } from '$lib/utils';
	import type { ObjectImage } from '$lib/fetch/objects/object-data';

	interface Props {
		image: ObjectImage | null;
		attribution: Attribution | null;
	}

	let { image, attribution }: Props = $props();

	// External Commons/Wikidata metadata — validate the scheme before it reaches
	// an href so a `javascript:` URL can't ride in.
	const safeLicenseUrl = $derived(safeHttpUrl(attribution?.license_url));
	const safeSourceUrl = $derived(safeHttpUrl(image?.source_url));

	let expanded = $state(false);
	let viewportRef = $state<HTMLElement | null>(null);
	let truncated = $state(false);

	// Bare `image;` is a Svelte effect dep read; eslint can't see the intent.
	$effect(() => {
		// eslint-disable-next-line @typescript-eslint/no-unused-expressions
		image;
		expanded = false;
	});

	const paragraphs = $derived(
		attribution?.description ? attribution.description.split('\n').filter((p) => p.trim()) : []
	);
	const hasExplicitBreaks = $derived((attribution?.description ?? '').includes('\n'));

	// Bare reads below are Svelte deps; ResizeObserver alone wouldn't fire when
	// max-height stays constant but paragraphs grow.
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

	// PhotoSwipe's wheelToZoom listens on the viewer container, so wheel events
	// bubbling out of the description's scroll viewport get hijacked into zoom.
	// overscroll-behavior: contain only stops scroll-chaining at the boundary,
	// not the bubble. Stop propagation while we're inside the scrollable range.
	$effect(() => {
		const el = viewportRef;
		if (!el) return;
		const onWheel = (e: WheelEvent) => {
			e.stopPropagation();
		};
		el.addEventListener('wheel', onWheel, { passive: true });
		return () => el.removeEventListener('wheel', onWheel);
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
			{#if safeLicenseUrl}
				<a
					href={safeLicenseUrl}
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
		{#if safeSourceUrl}
			<a
				href={safeSourceUrl}
				target="_blank"
				rel="noopener noreferrer"
				class="inline-flex items-center gap-1"
				>{m.image_view_on_commons()}<ExternalLinkIcon class="size-3 shrink-0" /></a
			>
		{/if}
	</div>
{/if}
