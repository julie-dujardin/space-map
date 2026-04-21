<script lang="ts">
	import { X } from '@lucide/svelte';
	import { Portal } from 'bits-ui';
	import { getLocale } from '$lib/paraglide/runtime.js';
	import * as m from '$lib/paraglide/messages.js';
	import type { ObjectImage } from '$lib/fetch/objects/object-data';

	interface Props {
		image: ObjectImage;
		alt: string;
		onClose: () => void;
	}

	let { image, alt, onClose }: Props = $props();

	const fullSrc = $derived(`/data/v1/images/full/${image.file}`);
	const metadataSrc = $derived(`/data/v1/images/metadata/${encodeURIComponent(image.file)}.json`);

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

	// Detect whether the clamped description actually overflows 2 lines.
	// Skipped while expanded (line-clamp is off, so the measurement is useless).
	$effect(() => {
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

	function onKeyDown(event: KeyboardEvent) {
		if (event.key === 'Escape') onClose();
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

	/** HTML-strip, entity-decode, whitespace-collapse. */
	function plainText(field: ExtField | undefined, strictLocale = false): string | undefined {
		if (!field?.value) return undefined;
		const raw = pickLang(field.value, strictLocale);
		if (!raw) return undefined;
		// `innerHTML` parses but doesn't execute scripts (HTML5 spec); using
		// `.textContent` then gives us a safely-stripped plain-text version.
		const tmp = document.createElement('div');
		tmp.innerHTML = raw;
		const text = (tmp.textContent ?? '').replace(/\s+/g, ' ').trim();
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
		data-vaul-no-drag
		class="fixed inset-0 z-[100] md:left-[380px] flex items-center justify-center bg-black/85 backdrop-blur-sm"
	>
		<!-- Backdrop click area: full panel, below the image. Uses a button so the
	     interaction is keyboard-accessible even though the Escape key is the
	     primary close path. -->
		<button
			type="button"
			aria-label={m.close()}
			onclick={onClose}
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

		<!-- Mobile (<md): stacked column, description on top, credits pill at bottom-right.
		     Desktop (md+): row layout, description on the left (content-sized, capped at 50%),
		     credits pill pushed to the right (also capped at 50%). -->
		<div
			class="pointer-events-none absolute inset-x-0 bottom-0 z-20 flex flex-col
			md:flex-row md:items-end"
		>
			{#if attribution?.description}
				<div
					class="pointer-events-auto flex w-full max-h-[33vh] flex-col gap-1 overflow-y-auto
					overscroll-contain bg-black/50 px-4 py-2.5 text-sm leading-snug text-white/85
					backdrop-blur-md md:w-fit md:max-w-[50%]"
				>
					<p bind:this={descriptionEl} class={descriptionExpanded ? '' : 'line-clamp-2'}>
						{attribution.description}
					</p>
					{#if descriptionTruncated}
						<button
							type="button"
							onclick={() => (descriptionExpanded = !descriptionExpanded)}
							class="self-start text-xs text-white/60 hover:text-white"
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
					href={image.source_url}
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
