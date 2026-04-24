<script lang="ts">
	import { getContext } from 'svelte';
	import { ChevronLeft, ChevronRight, X } from '@lucide/svelte';
	import { Portal } from 'bits-ui';
	import { getLocale } from '$lib/paraglide/runtime.js';
	import * as m from '$lib/paraglide/messages.js';
	import { ScrollArea } from '$lib/components/ui/scroll-area/index.js';
	import type { ObjectImage } from '$lib/fetch/objects/object-data';
	import { DATA_BASE } from '$lib/fetch/data-base';
	import type { AppState } from '$lib/state/app-state.svelte';

	interface Props {
		images: ObjectImage[];
		alt: string;
		onClose: () => void;
	}

	let { images, alt, onClose }: Props = $props();

	const appState = getContext<AppState>('appState');

	// Clamp to valid range so a stale/out-of-range `img=` in the URL doesn't
	// blow up the `images[index]` access. ObjectHeader already guards the null
	// case (viewer isn't mounted when imageIndex is null).
	const index = $derived(Math.min(Math.max(appState.view.imageIndex ?? 0, 0), images.length - 1));
	const currentImage = $derived(images[index]);
	const fullSrc = $derived(`${DATA_BASE}/v1/images/full/${currentImage.file}`);
	const metadataSrc = $derived(
		`${DATA_BASE}/v1/images/metadata/${encodeURIComponent(currentImage.file)}.json`
	);

	const hasMultiple = $derived(images.length > 1);
	const hasPrev = $derived(index > 0);
	const hasNext = $derived(index < images.length - 1);

	function goPrev() {
		if (hasPrev) appState.setImage(index - 1);
	}
	function goNext() {
		if (hasNext) appState.setImage(index + 1);
	}

	interface Attribution {
		license?: string;
		license_url?: string;
		artist?: string;
		description?: string;
	}

	let attribution = $state<Attribution | null>(null);
	let descriptionExpanded = $state(false);
	let descriptionEl = $state<HTMLElement | undefined>();
	// Sticky: once we observe overflow under line-clamp, keep the toggle visible
	// even after expansion so the user can collapse again.
	let descriptionTruncated = $state(false);

	// Reset per-image UI state on navigation so each image gets a fresh
	// attribution fetch and description measurement.
	$effect(() => {
		void index;
		attribution = null;
		descriptionExpanded = false;
		descriptionTruncated = false;
	});

	// Fetch attribution lazily on open — the exported metadata JSON alongside
	// each image is the single source of truth. Not embedded in the per-object
	// JSON because (a) it'd duplicate data across tens of thousands of object
	// files, (b) the viewer is the only place that actually renders it.
	$effect(() => {
		const url = metadataSrc;
		let cancelled = false;
		fetch(url)
			.then((r) => (r.ok ? r.json() : null))
			.then((meta) => {
				if (cancelled || !meta) return;
				attribution = extractAttribution(meta);
			})
			.catch(() => {
				/* Missing / malformed metadata — fall back to Commons link only. */
			});
		return () => {
			cancelled = true;
		};
	});

	// Detect whether the clamped description actually overflows 2 lines, or
	// hides additional paragraphs that only appear on expansion. Skipped while
	// expanded (line-clamp is off, so the visual measurement is useless then).
	$effect(() => {
		if (attribution?.description?.includes('\n')) descriptionTruncated = true;
		const el = descriptionEl;
		if (!el || descriptionExpanded) return;
		const check = () => {
			if (el.scrollHeight > el.clientHeight + 1) descriptionTruncated = true;
		};
		check();
		const ro = new ResizeObserver(check);
		ro.observe(el);
		return () => ro.disconnect();
	});

	// Preload neighbours so arrow/wheel navigation flips instantly.
	$effect(() => {
		if (!hasMultiple) return;
		const neighbours = [index - 1, index + 1].filter((i) => i >= 0 && i < images.length);
		for (const i of neighbours) {
			const img = new Image();
			img.src = `${DATA_BASE}/v1/images/full/${images[i].file}`;
		}
	});

	function onKeyDown(event: KeyboardEvent) {
		if (event.key === 'Escape') onClose();
		else if (event.key === 'ArrowLeft') goPrev();
		else if (event.key === 'ArrowRight') goNext();
		else if (event.key === 'Home') appState.setImage(0);
		else if (event.key === 'End') appState.setImage(images.length - 1);
	}

	// Horizontal touch-swipe navigation. Tracked via pointer events so the
	// backdrop button below the image doesn't turn a swipe into a close-tap.
	// Vertical movement falls through to the description scroll area.
	const SWIPE_THRESHOLD = 50;
	let touchStartX = 0;
	let touchStartY = 0;
	let swiping = false;
	// Set on successful swipe so the synthesized click on pointerup (which the
	// backdrop button would otherwise receive as a close) is dropped.
	let suppressNextClick = false;

	function onPointerDown(event: PointerEvent) {
		if (event.pointerType !== 'touch' || !hasMultiple) return;
		touchStartX = event.clientX;
		touchStartY = event.clientY;
		swiping = false;
	}

	function onPointerMove(event: PointerEvent) {
		if (event.pointerType !== 'touch' || !hasMultiple) return;
		const dx = event.clientX - touchStartX;
		const dy = event.clientY - touchStartY;
		if (!swiping && Math.abs(dx) > 10 && Math.abs(dx) > Math.abs(dy)) {
			swiping = true;
		}
	}

	function onPointerUp(event: PointerEvent) {
		if (event.pointerType !== 'touch' || !swiping) return;
		const dx = event.clientX - touchStartX;
		swiping = false;
		if (Math.abs(dx) < SWIPE_THRESHOLD) return;
		suppressNextClick = true;
		if (dx < 0) goNext();
		else goPrev();
	}

	function onBackdropClick() {
		if (suppressNextClick) {
			suppressNextClick = false;
			return;
		}
		onClose();
	}

	// --- extmetadata helpers -------------------------------------------------

	interface ExtField {
		value?: string | Record<string, string> | null;
	}

	type ExtMeta = Record<string, ExtField | undefined>;

	interface CommonsMetadata {
		imageinfo?: { extmetadata?: ExtMeta };
	}

	function extractAttribution(meta: CommonsMetadata): Attribution {
		const em = meta.imageinfo?.extmetadata ?? {};
		return {
			license: plainText(em.LicenseShortName),
			license_url: plainUrl(em.LicenseUrl),
			artist: plainText(em.Artist) ?? plainText(em.Credit),
			// For descriptions, a multilang fallback to an arbitrary language
			// would be unreadable, so we only pick the user's own locale. Bare
			// (unlocalized) strings are always shown if nothing better is available.
			description: plainText(em.ImageDescription, true)
		};
	}

	/** Pick the best language variant from an extmetadata field value.
	 *  Commons returns either a bare string or `{_type: "lang", en: ..., fr: ...}`
	 *  when we passed `iiextmetadatamultilang=1` at download time.
	 *  With `strictLocale`, a multilang value is only returned for the user's
	 *  current locale; bare strings are always returned regardless. */
	function pickLang(value: string | Record<string, string>, strictLocale = false): string {
		if (typeof value === 'string') return value;
		const locale = getLocale();
		if (typeof value[locale] === 'string') return value[locale];
		if (strictLocale) return '';
		if (typeof value.en === 'string') return value.en;
		for (const [k, v] of Object.entries(value)) {
			if (k !== '_type' && typeof v === 'string') return v;
		}
		return '';
	}

	/** HTML-strip, entity-decode, whitespace-collapse. Block elements (p, div, li)
	 *  and <br> are converted to newlines so paragraph structure survives for
	 *  callers that want to render it (e.g. the image description). */
	function plainText(field: ExtField | undefined, strictLocale = false): string | undefined {
		if (!field?.value) return undefined;
		const raw = pickLang(field.value, strictLocale);
		if (!raw) return undefined;
		// `innerHTML` parses but doesn't execute scripts (HTML5 spec); using
		// `.textContent` then gives us a safely-stripped plain-text version.
		const tmp = document.createElement('div');
		tmp.innerHTML = raw;
		for (const br of tmp.querySelectorAll('br')) br.replaceWith('\n');
		for (const block of tmp.querySelectorAll('p, div, li')) block.append('\n\n');
		const text = (tmp.textContent ?? '')
			// Collapse non-newline whitespace runs; keep newlines intact.
			.replace(/[^\S\n]+/g, ' ')
			// Normalize any run of 2+ newlines to exactly one blank line.
			.replace(/\n{2,}/g, '\n\n')
			.trim();
		return text || undefined;
	}

	function plainUrl(field: ExtField | undefined): string | undefined {
		if (typeof field?.value !== 'string') return undefined;
		const s = field.value.trim();
		return s || undefined;
	}
</script>

<svelte:window onkeydown={onKeyDown} />

<!-- Portalled to document.body so the viewer escapes the drawer's stacking
     context (Vaul.Content uses a CSS transform which traps child z-index).
     Desktop: offset from the 380px left sidebar so the detail panel stays visible.
     Mobile (<md): full viewport. Attribution overlays the image bottom; capped at
     a third of the viewport so long credit strings don't dominate. -->
<Portal>
	<div
		role="dialog"
		aria-modal="true"
		aria-label={alt}
		tabindex={-1}
		data-vaul-no-drag
		onpointerdown={onPointerDown}
		onpointermove={onPointerMove}
		onpointerup={onPointerUp}
		onpointercancel={() => (swiping = false)}
		class="fixed inset-0 z-[100] md:left-[380px] flex touch-none items-center justify-center bg-black/85 backdrop-blur-sm"
	>
		<!-- Backdrop click area: full panel, below the image. Uses a button so the
	     interaction is keyboard-accessible even though the Escape key is the
	     primary close path. -->
		<button
			type="button"
			aria-label={m.close()}
			onclick={onBackdropClick}
			class="absolute inset-0 cursor-zoom-out"
		></button>

		<img
			src={fullSrc}
			{alt}
			class="relative z-10 max-h-[100vh] max-w-full object-contain pointer-events-none"
		/>

		<button
			type="button"
			onclick={onClose}
			aria-label={m.close()}
			class="absolute top-3 right-3 z-20 flex h-9 w-9 items-center justify-center
			rounded-full bg-black/55 text-white/90 backdrop-blur-sm
			hover:bg-black/75 hover:text-white transition-colors"
		>
			<X class="h-5 w-5" aria-hidden="true" />
		</button>

		{#if hasMultiple}
			<div
				class="absolute top-3 left-3 z-20 rounded-full bg-black/55 px-3 py-1.5
				text-xs font-medium text-white/90 tabular-nums backdrop-blur-sm"
				aria-live="polite"
			>
				{index + 1} / {images.length}
			</div>

			<button
				type="button"
				onclick={goPrev}
				disabled={!hasPrev}
				aria-label={m.image_previous()}
				class="absolute top-1/2 left-3 z-20 flex h-10 w-10 -translate-y-1/2
				items-center justify-center rounded-full bg-black/55 text-white/90
				backdrop-blur-sm transition-colors hover:bg-black/75 hover:text-white
				disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:bg-black/55
				disabled:hover:text-white/90"
			>
				<ChevronLeft class="h-6 w-6" aria-hidden="true" />
			</button>
			<button
				type="button"
				onclick={goNext}
				disabled={!hasNext}
				aria-label={m.image_next()}
				class="absolute top-1/2 right-3 z-20 flex h-10 w-10 -translate-y-1/2
				items-center justify-center rounded-full bg-black/55 text-white/90
				backdrop-blur-sm transition-colors hover:bg-black/75 hover:text-white
				disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:bg-black/55
				disabled:hover:text-white/90"
			>
				<ChevronRight class="h-6 w-6" aria-hidden="true" />
			</button>
		{/if}

		<!-- Mobile (<md): stacked column, description on top, credits pill at bottom-right.
		     Desktop (md+): row layout, description on the left (content-sized, capped at 50%),
		     credits pill pushed to the right (also capped at 50%). -->
		<div
			class="pointer-events-none absolute inset-x-0 bottom-0 z-20 flex flex-col
			md:flex-row md:items-end"
		>
			{#if attribution?.description}
				<div
					class="pointer-events-auto flex w-full flex-col gap-2 bg-black/50 py-2.5
					text-sm leading-snug text-white/85 backdrop-blur-md md:w-fit md:max-w-[50%]
					{descriptionExpanded ? 'max-h-[33vh]' : ''}"
				>
					{#if descriptionExpanded}
						<ScrollArea class="min-h-0 flex-1 touch-pan-y overscroll-contain">
							<div class="flex flex-col gap-2 ps-4 pe-2">
								{#each attribution.description.split('\n') as paragraph, i (i)}
									{#if paragraph.trim()}
										<p>{paragraph}</p>
									{/if}
								{/each}
							</div>
						</ScrollArea>
					{:else}
						<div
							bind:this={descriptionEl}
							class="flex max-h-[3lh] flex-col gap-2 overflow-hidden px-4"
						>
							{#each attribution.description.split('\n') as paragraph, i (i)}
								{#if paragraph.trim()}
									<p>{paragraph}</p>
								{/if}
							{/each}
						</div>
					{/if}
					{#if descriptionTruncated}
						<button
							type="button"
							onclick={() => (descriptionExpanded = !descriptionExpanded)}
							class="mx-4 self-start text-xs text-white/60 hover:text-white"
						>
							{descriptionExpanded ? m.show_less() : m.read_more()}
						</button>
					{/if}
				</div>
			{/if}
			<div
				class="pointer-events-auto flex max-w-full items-center gap-1.5 self-end
				overflow-hidden rounded-s-sm bg-black/40 px-2 py-1 text-[11px] leading-tight
				text-white/75 whitespace-nowrap backdrop-blur-sm md:ms-auto md:max-w-[50%]"
			>
				{#if attribution?.license}
					{#if attribution.license_url}
						<a
							href={attribution.license_url}
							target="_blank"
							rel="noopener noreferrer license"
							class="underline decoration-white/40 hover:text-white hover:decoration-white"
						>
							{attribution.license}
						</a>
					{:else}
						<span>{attribution.license}</span>
					{/if}
					<span class="text-white/40" aria-hidden="true">·</span>
				{/if}
				{#if attribution?.artist}
					<span class="min-w-0 truncate">
						{attribution.artist}
					</span>
					<span class="text-white/40" aria-hidden="true">·</span>
				{/if}
				<a
					href={currentImage.source_url}
					target="_blank"
					rel="noopener noreferrer"
					class="underline decoration-white/40 hover:text-white hover:decoration-white"
				>
					{m.image_view_on_commons()}
				</a>
			</div>
		</div>
	</div>
</Portal>
