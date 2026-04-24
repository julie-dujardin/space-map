<script lang="ts">
	import { getContext, onMount } from 'svelte';
	import PhotoSwipe from 'photoswipe';
	import 'photoswipe/style.css';
	import { getLocale } from '$lib/paraglide/runtime.js';
	import * as m from '$lib/paraglide/messages.js';
	import type { ObjectImage } from '$lib/fetch/objects/object-data';
	import { fetchImageMetadata, variantUrl, type ImageMetadata } from '$lib/fetch/objects/images';
	import type { AppState } from '$lib/state/app-state.svelte';

	interface Props {
		images: ObjectImage[];
		alt: string;
		onClose: () => void;
	}

	let { images, alt, onClose }: Props = $props();

	const appState = getContext<AppState>('appState');

	// Pick the largest available variant. PhotoSwipe is a zoomable fullscreen
	// viewer, so we always want the highest-res bucket the exporter produced —
	// leaving srcset to the browser picks the 's' variant on narrow viewports
	// and defeats the point of opening the viewer.
	function largestVariant(image: ObjectImage): string {
		return variantUrl(image, 'xl') ?? variantUrl(image, 'm') ?? variantUrl(image, 's') ?? '';
	}

	// Measure aspect ratio off the smallest variant so opening stays fast. The
	// fullscreen image's true natural dimensions arrive later on `loadComplete`.
	function measureAspect(src: string): Promise<{ w: number; h: number }> {
		return new Promise((resolve) => {
			const img = new Image();
			img.onload = () => resolve({ w: img.naturalWidth || 1, h: img.naturalHeight || 1 });
			img.onerror = () => resolve({ w: 1, h: 1 });
			img.src = src;
		});
	}

	const SIDEBAR_WIDTH = 380;
	const SIDEBAR_BREAKPOINT = 768;

	// PhotoSwipe defaults to `documentElement.clientWidth` for its internal
	// viewport, which ignores our CSS-shifted left edge — slides end up
	// centered relative to the full window, leaving the image visually offset
	// to the right. Subtracting the sidebar width here re-centers them in the
	// visible area.
	function viewportSize() {
		const offset = window.innerWidth >= SIDEBAR_BREAKPOINT ? SIDEBAR_WIDTH : 0;
		return { x: window.innerWidth - offset, y: window.innerHeight };
	}

	let pswp: PhotoSwipe | null = null;

	// Keep PhotoSwipe in sync when `imageIndex` changes externally (browser
	// back/forward, or any other path that mutates app state without going
	// through pswp itself). The 'change' handler guards the opposite direction
	// by reading currIndex before calling setImage.
	$effect(() => {
		const target = appState.view.imageIndex;
		if (pswp && target !== null && target !== pswp.currIndex) {
			pswp.goTo(target);
		}
	});

	onMount(() => {
		let teardown = false;
		// Set to true when the host (Svelte) unmounts us, so the pswp 'destroy'
		// handler doesn't bounce back into onClose and cause a double close.
		let suppressCloseCallback = false;

		const initialIndex = Math.min(Math.max(appState.view.imageIndex ?? 0, 0), images.length - 1);

		(async () => {
			const dataSource = await Promise.all(
				images.map(async (image) => {
					const src = largestVariant(image);
					// Open with the small variant's dimensions — display fits viewport
					// via zoomLevels.initial, which scales to any aspect-preserving
					// pair. loadComplete replaces these with the true natural size
					// (and recomputes zoom) once the full-res image loads so max-zoom
					// reveals the real pixels.
					const measureSrc = variantUrl(image, 's') ?? src;
					const { w, h } = await measureAspect(measureSrc);
					return { src, width: w, height: h, alt, image };
				})
			);

			if (teardown) return;

			pswp = new PhotoSwipe({
				dataSource,
				index: initialIndex,
				bgOpacity: 0.9,
				showHideAnimationType: 'fade',
				closeOnVerticalDrag: true,
				wheelToZoom: true,
				mainClass: 'pswp-space-map',
				getViewportSizeFn: viewportSize,
				closeTitle: m.close(),
				arrowPrevTitle: m.image_previous(),
				arrowNextTitle: m.image_next()
			});

			// Swap in the image's true natural size once it loads. We open with the
			// small variant's dimensions, so without this the slide stays sized to
			// the thumbnail (zoomLevels.initial was computed off those) and the
			// user gets the small-variant scale even for the full-res image. We
			// must re-run calculateSize so zoomLevels.initial reflects the new
			// dims, and zoomAndPanToInitial re-centers to that new zoom level.
			pswp.on('loadComplete', (e) => {
				const content = e.content;
				const el = content.element;
				if (!(el instanceof HTMLImageElement)) return;
				const nw = el.naturalWidth;
				const nh = el.naturalHeight;
				if (!nw || !nh) return;
				if (content.width === nw && content.height === nh) return;
				content.width = nw;
				content.height = nh;
				content.data.width = nw;
				content.data.height = nh;
				const slide = content.slide;
				if (slide) {
					slide.width = nw;
					slide.height = nh;
					slide.calculateSize();
					slide.zoomAndPanToInitial();
					slide.updateContentSize(true);
				}
			});

			// Mark the pswp root so Vaul ignores it for drawer-drag detection.
			// Independently, Vaul's iOS prevent-scroll walks up `getScrollParent`
			// from the touch target and preventDefaults touchmove when it hits
			// documentElement — which blocks the browser from synthesizing the
			// pointermove events PhotoSwipe relies on. Marking scroll-wrap as
			// `overflow: auto` (via CSS below) gives that walk a stopping point
			// with zero scroll range, so Vaul bails out instead of blocking.
			pswp.on('afterInit', () => {
				pswp!.element?.setAttribute('data-vaul-no-drag', '');
			});

			pswp.on('uiRegister', () => {
				pswp!.ui!.registerElement({
					name: 'space-map-caption',
					appendTo: 'root',
					onInit: (rootEl) => attachCaption(rootEl, pswp!)
				});
			});

			pswp.on('change', () => {
				appState.setImage(pswp!.currIndex);
			});

			pswp.on('destroy', () => {
				pswp = null;
				if (!suppressCloseCallback) onClose();
			});

			pswp.init();
		})();

		return () => {
			teardown = true;
			if (pswp) {
				suppressCloseCallback = true;
				pswp.destroy();
			}
		};
	});

	// --- caption DOM -------------------------------------------------------------

	interface Attribution {
		license?: string;
		license_url?: string;
		artist?: string;
		description?: string;
	}

	const metadataCache = new Map<string, Promise<ImageMetadata | null>>();

	function getMetadata(image: ObjectImage): Promise<ImageMetadata | null> {
		let p = metadataCache.get(image.file);
		if (!p) {
			p = fetchImageMetadata(image).catch(() => null);
			metadataCache.set(image.file, p);
		}
		return p;
	}

	// Builds the caption subtree once, then updates its contents as the user
	// navigates. Kept imperative because PhotoSwipe owns the DOM tree it lives
	// in — mounting a Svelte child here would fight PhotoSwipe's lifecycle.
	function attachCaption(root: HTMLElement, pswp: PhotoSwipe) {
		root.className = 'pswp-sm-caption-root';

		const descWrap = document.createElement('div');
		descWrap.className = 'pswp-sm-caption-desc-wrap';
		const descBody = document.createElement('div');
		descBody.className = 'pswp-sm-caption-desc';
		const toggleBtn = document.createElement('button');
		toggleBtn.type = 'button';
		toggleBtn.className = 'pswp-sm-caption-toggle';
		descWrap.append(descBody, toggleBtn);

		const credits = document.createElement('div');
		credits.className = 'pswp-sm-caption-credits';

		root.append(descWrap, credits);

		let expanded = false;
		// Fetch token: each render bumps it, so a slow metadata fetch from a prior
		// slide can't overwrite the caption for the slide the user is now on.
		let fetchToken = 0;

		function setExpanded(next: boolean) {
			expanded = next;
			descWrap.classList.toggle('is-expanded', expanded);
			toggleBtn.textContent = expanded ? m.show_less() : m.read_more();
		}

		toggleBtn.addEventListener('click', (e) => {
			e.stopPropagation();
			setExpanded(!expanded);
		});

		// Clamp detection: only show the toggle when the collapsed description
		// actually overflows, or when we know there are more paragraphs hidden
		// under the line-clamp (explicit newlines in the source).
		const ro = new ResizeObserver(() => updateTruncation());
		ro.observe(descBody);

		let hasExplicitBreaks = false;

		function updateTruncation() {
			if (expanded) return;
			const overflows = descBody.scrollHeight > descBody.clientHeight + 1;
			descWrap.classList.toggle('is-truncated', overflows || hasExplicitBreaks);
		}

		function renderDescription(text: string | undefined) {
			descBody.replaceChildren();
			if (!text) {
				descWrap.style.display = 'none';
				return;
			}
			descWrap.style.display = '';
			const paragraphs = text.split('\n').filter((p) => p.trim());
			for (const p of paragraphs) {
				const el = document.createElement('p');
				el.textContent = p;
				descBody.append(el);
			}
			hasExplicitBreaks = text.includes('\n');
			updateTruncation();
		}

		function renderCredits(image: ObjectImage, attribution: Attribution | null) {
			credits.replaceChildren();
			const parts: (Node | string)[] = [];
			if (attribution?.license) {
				if (attribution.license_url) {
					const a = document.createElement('a');
					a.href = attribution.license_url;
					a.target = '_blank';
					a.rel = 'noopener noreferrer license';
					a.textContent = attribution.license;
					parts.push(a);
				} else {
					parts.push(attribution.license);
				}
			}
			if (attribution?.artist) {
				const span = document.createElement('span');
				span.className = 'pswp-sm-caption-artist';
				span.textContent = attribution.artist;
				parts.push(span);
			}
			const source = document.createElement('a');
			source.href = image.source_url;
			source.target = '_blank';
			source.rel = 'noopener noreferrer';
			source.textContent = m.image_view_on_commons();
			parts.push(source);

			parts.forEach((part, i) => {
				if (i > 0) {
					const sep = document.createElement('span');
					sep.className = 'pswp-sm-caption-sep';
					sep.setAttribute('aria-hidden', 'true');
					sep.textContent = '·';
					credits.append(sep);
				}
				credits.append(part);
			});
		}

		async function render() {
			const index = pswp.currIndex;
			const image = images[index];
			if (!image) return;

			setExpanded(false);
			descWrap.classList.remove('is-truncated');

			const token = ++fetchToken;
			const meta = await getMetadata(image);
			if (token !== fetchToken) return;

			const attribution = meta ? extractAttribution(meta) : null;
			renderDescription(attribution?.description);
			renderCredits(image, attribution);
			updateTruncation();
		}

		pswp.on('change', render);
		render();

		pswp.on('destroy', () => ro.disconnect());
	}

	// --- metadata helpers --------------------------------------------------------

	function extractAttribution(meta: ImageMetadata): Attribution {
		return {
			license: meta.license?.name,
			license_url: meta.license?.url,
			artist: plainText(meta.artist),
			// For descriptions, a multilang fallback to an arbitrary language
			// would be unreadable, so we only pick the user's own locale. Bare
			// (unlocalized) strings are always shown if nothing better is available.
			description: plainText(meta.description, true)
		};
	}

	/** Resolve a trimmed multilang field to a plain-text string.
	 *
	 *  The exporter writes bare strings when Commons didn't return a multilang
	 *  blob and `{<locale>: str}` dicts (restricted to supported locales) when
	 *  it did. HTML from Commons still passes through — we strip it here.
	 *  With `strictLocale`, a dict is only resolved for the current locale;
	 *  bare strings are always returned regardless. */
	function plainText(
		value: string | Record<string, string> | undefined,
		strictLocale = false
	): string | undefined {
		if (value === undefined) return undefined;
		const raw = typeof value === 'string' ? value : pickLang(value, strictLocale);
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

	function pickLang(value: Record<string, string>, strictLocale: boolean): string {
		const locale = getLocale();
		if (typeof value[locale] === 'string') return value[locale];
		if (strictLocale) return '';
		if (typeof value.en === 'string') return value.en;
		for (const v of Object.values(value)) {
			if (typeof v === 'string') return v;
		}
		return '';
	}
</script>

<style>
	/* Offset the whole modal past the desktop sidebar (380px) so the detail
	   panel stays visible. On mobile we let PhotoSwipe take the full viewport. */
	:global(.pswp.pswp-space-map) {
		--pswp-bg: #000;
	}
	@media (min-width: 768px) {
		:global(.pswp.pswp-space-map) {
			left: 380px;
			right: 0;
			width: auto;
		}
	}

	/* Stop Vaul's iOS prevent-scroll from hijacking touches inside the viewer.
	   Vaul walks up `getScrollParent` from the touch target and preventDefaults
	   the touchmove when it reaches documentElement — which also suppresses
	   pointermove synthesis on iOS, so PhotoSwipe's swipe/pan never fires.
	   Giving scroll-wrap `overflow: auto` (with zero scroll range since
	   PhotoSwipe still clips its children) makes Vaul's walk stop here and
	   short-circuit via its `bottom === 0` early return. */
	:global(.pswp-space-map .pswp__scroll-wrap) {
		overflow: auto;
	}

	/* Caption container: pinned to the bottom of the pswp root, above slides.
	   Mobile stacks description over credits; desktop puts them side-by-side. */
	:global(.pswp-space-map .pswp-sm-caption-root) {
		position: absolute;
		inset-inline: 0;
		bottom: 0;
		z-index: 1600;
		display: flex;
		flex-direction: column;
		pointer-events: none;
	}
	@media (min-width: 768px) {
		:global(.pswp-space-map .pswp-sm-caption-root) {
			flex-direction: row;
			align-items: flex-end;
		}
	}

	:global(.pswp-space-map .pswp-sm-caption-desc-wrap) {
		pointer-events: auto;
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
		width: 100%;
		padding: 0.625rem 0;
		font-size: 0.875rem;
		line-height: 1.25;
		color: rgba(255, 255, 255, 0.85);
		background: rgba(0, 0, 0, 0.55);
		backdrop-filter: blur(10px);
		-webkit-backdrop-filter: blur(10px);
	}
	@media (min-width: 768px) {
		:global(.pswp-space-map .pswp-sm-caption-desc-wrap) {
			width: fit-content;
			max-width: 50%;
		}
	}

	:global(.pswp-space-map .pswp-sm-caption-desc) {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
		padding: 0 1rem;
		overflow: hidden;
		max-height: 3lh;
	}
	:global(.pswp-space-map .pswp-sm-caption-desc p) {
		margin: 0;
	}

	:global(.pswp-space-map .pswp-sm-caption-desc-wrap.is-expanded) {
		max-height: 40vh;
	}
	:global(.pswp-space-map .pswp-sm-caption-desc-wrap.is-expanded .pswp-sm-caption-desc) {
		max-height: none;
		overflow-y: auto;
		overscroll-behavior: contain;
		touch-action: pan-y;
		padding-right: 0.5rem;
	}

	:global(.pswp-space-map .pswp-sm-caption-toggle) {
		display: none;
		align-self: flex-start;
		margin: 0 1rem;
		padding: 0;
		font-size: 0.75rem;
		color: rgba(255, 255, 255, 0.6);
		background: none;
		border: 0;
		cursor: pointer;
	}
	:global(.pswp-space-map .pswp-sm-caption-toggle:hover) {
		color: #fff;
	}
	:global(.pswp-space-map .pswp-sm-caption-desc-wrap.is-truncated .pswp-sm-caption-toggle) {
		display: block;
	}

	:global(.pswp-space-map .pswp-sm-caption-credits) {
		pointer-events: auto;
		display: flex;
		align-items: center;
		gap: 0.375rem;
		align-self: flex-end;
		max-width: 100%;
		padding: 0.25rem 0.5rem;
		font-size: 11px;
		line-height: 1.1;
		color: rgba(255, 255, 255, 0.75);
		white-space: nowrap;
		overflow: hidden;
		background: rgba(0, 0, 0, 0.4);
		backdrop-filter: blur(4px);
		-webkit-backdrop-filter: blur(4px);
		border-start-start-radius: 2px;
	}
	@media (min-width: 768px) {
		:global(.pswp-space-map .pswp-sm-caption-credits) {
			margin-inline-start: auto;
			max-width: 50%;
		}
	}
	:global(.pswp-space-map .pswp-sm-caption-credits a) {
		color: inherit;
		text-decoration: underline;
		text-decoration-color: rgba(255, 255, 255, 0.4);
	}
	:global(.pswp-space-map .pswp-sm-caption-credits a:hover) {
		color: #fff;
		text-decoration-color: #fff;
	}
	:global(.pswp-space-map .pswp-sm-caption-artist) {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	:global(.pswp-space-map .pswp-sm-caption-sep) {
		color: rgba(255, 255, 255, 0.4);
	}
</style>
