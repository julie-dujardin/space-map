<!--
  Size comparison, full page: the row is the screen, and everything else floats
  over it. The list at the side is what is being compared; how that set is
  broken into pages is decided here, when it is drawn, from the sizes and the
  room the names under them need.

  Opening one of them maximizes it: the row keeps that object alone, its two
  neighbours in size stand in the strips on either side the way a band's do,
  and the object's own page takes the place of the list.
-->
<script lang="ts">
	import { setContext, untrack } from 'svelte';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import ChevronLeftIcon from '@lucide/svelte/icons/chevron-left';
	import ChevronRightIcon from '@lucide/svelte/icons/chevron-right';
	import ChevronsLeftIcon from '@lucide/svelte/icons/chevrons-left';
	import ExternalLinkIcon from '@lucide/svelte/icons/external-link';
	import MenuIcon from '@lucide/svelte/icons/menu';
	import PlusIcon from '@lucide/svelte/icons/plus';
	import XIcon from '@lucide/svelte/icons/x';
	import * as m from '$lib/paraglide/messages.js';
	import * as Popover from '$lib/components/ui/popover';
	import * as Tooltip from '$lib/components/ui/tooltip';
	import { ScrollArea } from '$lib/components/ui/scroll-area/index.js';
	import SiteNav from '../../components/nav/SiteNav.svelte';
	import DrawerSkeleton from '../../components/detail/DrawerSkeleton.svelte';
	import ComparePicker from '../../components/compare/ComparePicker.svelte';
	import CompareCreditBar from '../../components/compare/CompareCreditBar.svelte';
	import BodyLineup, { type LineupBody } from '../../components/detail/charts/BodyLineup.svelte';
	import { bandsBySize, screensOf } from '$lib/compare/pages';
	import { labelWidth, screenFit, SIDE_PAD } from '../../components/detail/charts/lineup-fit';
	import { lineupBody, resolveObject, type CompareObject } from '$lib/compare/geometry';
	import { COMPARE_PRESETS, presetOn, type ComparePreset } from '$lib/compare/presets';
	import type { ObjectHit } from '$lib/search/client';
	import { formatQuantity } from '$lib/format/quantities';
	import { isModifiedClick } from '$lib/modified-click';
	import { BODY_COLORS, DEFAULT_BODY_COLOR } from '$lib/constants';
	import { bodyHref, groupHref } from '$lib/state/url';
	import { compareFocusable, type CompareFocus } from '$lib/compare/detail';
	import { AppState } from '$lib/state/app-state.svelte';
	import { MapCover } from '$lib/state/map-cover.svelte';
	import { SimClock } from '$lib/scene/state/clock.svelte';
	import { dateToJD } from '$lib/time/jd';
	import { DEFAULT_VIEW, urlTypeFromId } from '$lib/state/view';
	import type { SizeScreen } from '$lib/compare/pages';
	import { loadComparables, pickComparable, type SizedComparable } from '$lib/compare/comparables';
	import { rocketBySlug } from '$lib/compare/rockets';

	let { data } = $props();

	/** Below this the rail has no room to stand beside the row. */
	const NARROW = 768;
	/** How far a finger travels before it counts as a page turn. */
	const SWIPE_PX = 60;
	/** The band of names the row draws under itself, with room under them for
	 *  the credit line in the corner. */
	const LABEL_ROW = 60;

	let innerWidth = $state(NARROW + 1);
	const narrow = $derived(innerWidth <= NARROW);

	let railOpen = $state(true);
	let pickerOpen = $state(false);
	let stageWidth = $state(0);
	let stageHeight = $state(0);
	let page = $state(0);
	let menu = $state<{ id: string; x: number; y: number } | null>(null);
	/** The strip and the pill on one side are one control: both light together. */
	let hot = $state<'prev' | 'next' | null>(null);
	let laid = $state<
		{ id: string; cx: number; cy: number; pr: number; radiusKm: number; aside?: 'start' | 'end' }[]
	>([]);

	/** Everyday objects the row can be measured against, and whether the reader
	 *  wants them. Empty until the model index lands. */
	let comparables = $state<SizedComparable[]>([]);
	let comparablesOn = $state(true);
	const COMPARABLES_KEY = 'compare:comparables';

	$effect(() => {
		loadComparables().then((all) => (comparables = all));
		try {
			comparablesOn = localStorage.getItem(COMPARABLES_KEY) !== 'off';
		} catch {
			// Storage withheld: the default stands for this visit.
		}
	});

	function toggleComparables(): void {
		comparablesOn = !comparablesOn;
		try {
			localStorage.setItem(COMPARABLES_KEY, comparablesOn ? 'on' : 'off');
		} catch {
			// Storage withheld: the choice lasts the session.
		}
	}

	const selected = $derived(data.selected);
	/** The object the page is opened on, or null while the whole row is drawn. */
	const opened = $derived(data.opened);

	// The panel is the map's own, so it wants the map's context: a view state to
	// read and write, a clock to date what it shows, and the cover claim its
	// mobile sheet takes. There is no scene here, so no `ctx` — every consumer
	// treats that as a body the scene has not loaded, which is what it is. The
	// view is detached from the address bar: this page's URL is its own.
	const appState = new AppState(DEFAULT_VIEW, { ownsUrl: false });
	setContext('appState', appState);
	setContext('mapCover', new MapCover());
	const clock = new SimClock(dateToJD(new Date()), true);

	/** Everything resolved so far, by id. An object is drawn as soon as its own
	 *  bundle answers; the ones still in flight simply aren't in the row yet. */
	let resolved = $state<Record<string, CompareObject>>({});
	/** Names from the search hit that added an object, so a row can be labelled
	 *  before its bundle lands. */
	const seeds = new Map<string, { name: string; type?: string; diameter_km?: number }>();
	const asked = new Set<string>();

	$effect(() => {
		for (const id of selected) {
			if (asked.has(id)) continue;
			asked.add(id);
			resolveObject(id, seeds.get(id) ?? { name: '' })
				.then((object) => {
					if (object) resolved[object.id] = object;
				})
				.catch(() => asked.delete(id));
		}
	});

	const objects = $derived(
		selected.map((id) => resolved[id]).filter((o): o is CompareObject => !!o)
	);
	const bands = $derived(bandsBySize(objects, (o) => o.radiusKm));
	/** Sorted for the side list: the row's own order, largest first. */
	const listed = $derived([...objects].sort((a, b) => b.radiusKm - a.radiusKm));
	/** A rocket with no family in the catalogue has no page to open. */
	const hasPage = (object: CompareObject) => object.geometry.href !== null;
	/** The object's own page, or its family's where that is what it has. */
	const pageHref = (object: CompareObject) =>
		object.geometry.href ?? bodyHref(object.id, object.name);
	/** The ones the row can maximize, in the list's order. */
	const openable = $derived(listed.filter(hasPage));

	/** The bands, cut again where their bodies and names run out of width,
	 *  each page as large as its own bodies allow. Until the stage is measured
	 *  there is one page per band, on the row's own scale. */
	const bandPages = $derived.by(() => {
		const rowHeight = stageHeight - LABEL_ROW;
		if (!stageWidth || rowHeight <= 0) {
			return screensOf(bands, (items) => ({ count: items.length, scale: 0 }));
		}
		const fit = (o: CompareObject) => ({
			radiusKm: o.radiusKm,
			label: labelWidth(o.name, sizeText(o)),
			aspect: o.geometry.aspect
		});
		return screensOf(bands, (rest, after, first) =>
			screenFit(rest.map(fit), after && fit(after), stageWidth, rowHeight, first)
		);
	});
	/** Maximized, every object with a page is one, and the list's own order is
	 *  what stands in the strips on either side. */
	const pages = $derived<SizeScreen<CompareObject>[]>(
		opened
			? openable.map((object, i) => ({
					items: [object],
					previous: openable[i - 1],
					next: openable[i + 1],
					scale: 0
				}))
			: bandPages
	);
	// A link from an object's own page lands on the page that holds it: banded
	// by size, the set it joins usually starts several pages above it. Waits for
	// the whole set and a measured stage, since both move the pages under it,
	// and lands once only — after that the page is the reader's.
	let landed = false;
	$effect(() => {
		// Both read before any test: a short-circuit here would drop one of them
		// as a dependency, and the landing would miss whichever arrived last.
		const measured = !!stageWidth;
		const whole = objects.length === selected.length;
		if (landed || !data.startOn || !measured || !whole) return;
		const home = bandPages.findIndex((p) => p.items.some((o) => o.id === data.startOn));
		if (home < 0) return;
		landed = true;
		untrack(() => (page = home));
	});

	const pageIndex = $derived(
		opened
			? Math.max(
					0,
					openable.findIndex((object) => object.id === opened)
				)
			: Math.min(page, Math.max(0, pages.length - 1))
	);
	const current = $derived(pages[pageIndex]);
	const bodies = $derived<LineupBody[]>(
		current
			? [
					...current.items.map(lineupBody),
					...(current.previous
						? [{ ...lineupBody(current.previous), aside: 'start' as const }]
						: []),
					...(current.next ? [{ ...lineupBody(current.next), aside: 'end' as const }] : [])
				]
			: []
	);

	// A shorter set can strand the reader on a page that no longer exists. Held
	// while one object is maximized, so closing it comes back to the page the
	// row was on.
	$effect(() => {
		if (!opened && page > pages.length - 1) page = Math.max(0, pages.length - 1);
	});

	/** Pixels per kilometre on this page, read off whatever the row laid out.
	 *  With no row there is no scale: the last layout is not reported undone. */
	const pxPerKm = $derived.by(() => {
		const first = bodies.length ? laid.find((l) => !l.aside) : undefined;
		return first ? first.pr / first.radiusKm : 0;
	});

	/** What this page is measured against: whatever comes out closest to the
	 *  target share of the stage, so turning the page can change it, and a page
	 *  that has left everyday sizes behind gets none. */
	const comparable = $derived(
		comparablesOn ? pickComparable(comparables, stageHeight, pxPerKm) : null
	);
	/** Drawn as a craft is: the mesh is the object, and it stands on the row's
	 *  own scale — which is the whole of what it claims. */
	const comparableBody = $derived<LineupBody | null>(
		comparable
			? {
					id: comparable.slug,
					name: comparable.label(),
					radiusKm: comparable.radiusKm,
					model: comparable.slug,
					craft: true,
					flat: comparable.flat,
					meshSpanRatio: comparable.meshSpanRatio,
					href: null
				}
			: null
	);
	/** How wide it comes out on this page's scale, and how tall the drawing is
	 *  at that width — a bus is mostly empty air in a square box. */
	const comparablePx = $derived(comparable ? comparable.radiusKm * 2 * pxPerKm : 0);
	/** What the mesh takes, which is the object plus anything drawn around it. */
	const comparableDrawn = $derived(comparablePx * (comparable?.meshSpanRatio ?? 1));
	/** Metres well past the kilometre, because a comparable is named by the
	 *  figure people know it as: Everest is 8,849 m, not 8.8 km. */
	const comparableSize = $derived.by(() => {
		const metres = (comparable?.radiusKm ?? 0) * 2000;
		return metres < 10_000
			? formatQuantity({ value: metres, unit: 'metre' }, true)
			: formatQuantity({ value: metres / 1000, unit: 'kilometre' }, true);
	});
	const comparableBox = $derived(Math.round(comparableDrawn));
	const comparableTall = $derived(Math.round(comparableDrawn * (comparable?.flatness ?? 1)));
	/** Below this it is a smudge, and says less than nothing there would. */
	const comparableFits = $derived(comparablePx >= 6);

	/** Where the row put the pages on either side of this one: what it drew of
	 *  them is also the way to them. */
	const ghostAt = $derived(laid.find((l) => l.aside === 'start'));
	const speckAt = $derived(laid.find((l) => l.aside === 'end'));

	function colorOf(object: CompareObject): string {
		return object.geometry.color ?? BODY_COLORS[object.id] ?? DEFAULT_BODY_COLOR;
	}

	function sizeText(object: CompareObject): string {
		const span = object.radiusKm * 2 * (object.geometry.meshSpanRatio ?? 1);
		return object.geometry.craft
			? formatQuantity({ value: span * 1000, unit: 'metre' }, true)
			: formatQuantity({ value: span, unit: 'kilometre' }, true);
	}

	// --- the set itself, which lives in the query string ---

	function compareHref(ids: readonly string[], open: string | null): string {
		return `${resolve('/compare')}?m=${ids.join(',')}${open ? `&o=${open}` : ''}`;
	}

	function go(ids: readonly string[], open: string | null): void {
		goto(compareHref(ids, open), {
			replaceState: true,
			noScroll: true,
			keepFocus: true
		});
	}

	function setIds(ids: readonly string[]): void {
		// An object dropped from the comparison has no page here any more.
		go(ids, opened && ids.includes(opened) ? opened : null);
	}

	/** Maximize one object, or (with null) come back to the whole row. Closing
	 *  lands on the page that holds the object, which is where the row zooms
	 *  back out to. */
	function openObject(id: string | null, slide?: -1 | 1): void {
		menu = null;
		if (id === opened || (id && resolved[id] && !hasPage(resolved[id]))) return;
		const subject = id ?? opened;
		if (!id && opened) {
			const home = bandPages.findIndex((p) => p.items.some((o) => o.id === opened));
			if (home >= 0) page = home;
		}
		startZoom(subject, slide);
		go(selected, id);
	}

	function addHit(hit: ObjectHit): void {
		seeds.set(hit.id, { name: hit.name, type: hit.type, diameter_km: hit.diameter_km });
		setIds([...selected, hit.id]);
		pickerOpen = false;
	}

	/** A preset is on when everything in it is up, however it got there. Turning
	 *  it on adds what is missing; turning it off takes its members away and
	 *  leaves the rest of the comparison standing. */
	function togglePreset(preset: ComparePreset): void {
		page = 0;
		setIds(
			presetOn(preset, selected)
				? selected.filter((id) => !preset.ids.includes(id))
				: [...selected, ...preset.ids.filter((id) => !selected.includes(id))]
		);
		pickerOpen = false;
	}

	function remove(id: string): void {
		menu = null;
		setIds(selected.filter((other) => other !== id));
	}

	// --- pages, which are only a way of drawing the set ---

	function turn(delta: number): void {
		const to = Math.min(Math.max(pageIndex + delta, 0), Math.max(0, pages.length - 1));
		menu = null;
		// Maximized, a page is an object: turning to one opens it, and the row
		// carries it in the way it was asked for.
		if (opened) {
			const next = pages[to]?.items[0];
			if (next) openObject(next.id, delta < 0 ? -1 : 1);
			return;
		}
		page = to;
	}

	let swipeFrom: number | null = null;
	function onSwipeStart(event: PointerEvent): void {
		swipeFrom = event.pointerType === 'touch' ? event.clientX : null;
	}
	function onSwipeEnd(event: PointerEvent): void {
		if (swipeFrom === null) return;
		const dx = event.clientX - swipeFrom;
		swipeFrom = null;
		if (Math.abs(dx) >= SWIPE_PX) turn(dx < 0 ? 1 : -1);
	}

	/** A round distance about 110 px long, for the bar the row is measured by.
	 *  With nothing to compare against it measures one lonely body whose size
	 *  the label under it already gives, so the row drops it. */
	const scaleBar = $derived.by(() => {
		if (!pxPerKm || objects.length < 2) return null;
		const raw = 110 / pxPerKm;
		const exponent = Math.floor(Math.log10(raw));
		const lead = raw / 10 ** exponent;
		const km = (lead >= 5 ? 5 : lead >= 2 ? 2 : 1) * 10 ** exponent;
		const label =
			km < 1
				? formatQuantity({ value: km * 1000, unit: 'metre' }, true)
				: formatQuantity({ value: km, unit: 'kilometre' }, true);
		return { px: km * pxPerKm, label };
	});

	// The row draws both neighbouring pages itself, at its own scale — the page
	// only names them.
	const ghost = $derived(current?.previous);
	const speck = $derived(current?.next);

	const menuObject = $derived(menu ? resolved[menu.id] : undefined);

	/** What the strip on either side leads to. Maximized it is the neighbouring
	 *  object itself; otherwise it is the page that object opens. */
	function neighbourLabel(object: CompareObject, n: number, terse = false): string {
		const parts = [object.name];
		if (!terse) parts.push(sizeText(object));
		if (!opened) parts.push(m.compare_page_of({ n }));
		return parts.join(' · ');
	}

	// --- zooming between the row and one object ---

	/** How long the row takes to grow into one object, or to fall back into
	 *  the comparison. */
	const ZOOM_MS = 420;
	/** How long the new row has to come up before the old picture starts to go. */
	const ZOOM_IN_MS = 200;
	const ZOOM_EASE = 'cubic-bezier(0.32, 0.72, 0, 1)';

	let row = $state<{ snapshot(): string | null } | undefined>();
	let rowBox = $state<HTMLDivElement | null>(null);

	/** The row as it stood before the change, held over the new one until the
	 *  two line up. Both are written about the object that was clicked, so it
	 *  never moves: the change reads as the row growing around it rather than
	 *  as one picture swapping for another. */
	let zoom = $state<{
		src: string;
		id: string;
		/** The canvas it was drawn on, in viewport pixels. */
		box: { left: number; top: number; width: number; height: number };
		/** Where the object stood on it, and whether that is somewhere the new
		 *  row can be pinned to: a body drawn as a neighbouring page's limb is
		 *  held to its strip rather than to its true size, so the two rows have
		 *  no common scale to grow along. */
		at: { cx: number; cy: number; pr: number };
		pin: boolean;
		/** A page turn rather than a zoom: one maximized object gives way to the
		 *  next, so the row carries the old one off and the new one on, the way
		 *  the strips and the swipe say it should. -1 draws from the start side,
		 *  1 from the end. */
		slide?: -1 | 1;
		/** What keeps the old picture where it was drawn while the stage moves
		 *  out from under it. */
		hold?: { dx: number; dy: number };
		/** Where each half starts and ends, once the new row is measured. */
		play?: { ghost: string; live: string };
		/** Set a frame later: a transform written in the same breath as the
		 *  transition that carries it has nothing to move from. */
		on?: boolean;
	} | null>(null);
	let zoomTimer: ReturnType<typeof setTimeout> | undefined;

	/** A reader who asked for less motion gets the change without the move. */
	const stillness = () =>
		typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

	function startZoom(id: string | null | undefined, slide?: -1 | 1): void {
		zoom = null;
		clearTimeout(zoomTimer);
		if (!id || !rowBox || stillness()) return;
		const at = laid.find((l) => l.id === id);
		const src = at && row?.snapshot();
		if (!at || !src) return;
		const box = rowBox.getBoundingClientRect();
		const held = {
			src,
			id,
			box: { left: box.left, top: box.top, width: box.width, height: box.height },
			at: { cx: at.cx, cy: at.cy, pr: at.pr },
			pin: !at.aside,
			slide
		};
		zoom = held;
		// Nothing else drops a picture that is never given a layout to move to.
		zoomTimer = setTimeout(() => {
			if (zoom === held) zoom = null;
		}, ZOOM_MS + 200);
	}

	/** The change has landed: pin the old picture where it was drawn, and wait
	 *  for the row to settle before measuring it. The stage takes its width
	 *  from a resize observer, which reports after the coming frame, and the
	 *  row is laid out from that. */
	function holdZoom(): void {
		const z = zoom;
		if (!z || z.hold || !rowBox) return;
		const box = rowBox.getBoundingClientRect();
		z.hold = { dx: z.box.left - box.left, dy: z.box.top - box.top };
		requestAnimationFrame(() => requestAnimationFrame(() => playZoom(z)));
	}

	/** Measure where the object ended up and set both halves moving. */
	function playZoom(z: NonNullable<typeof zoom>): void {
		if (zoom !== z || !rowBox) return;
		const to = laid.find((l) => l.id === z.id);
		const scale = z.pin && to && !to.aside ? to.pr / z.at.pr : 1;
		if (!(scale > 0) || !Number.isFinite(scale)) {
			zoom = null;
			return;
		}
		const box = rowBox.getBoundingClientRect();
		const dx = z.box.left - box.left;
		const dy = z.box.top - box.top;
		z.hold = { dx, dy };
		if (z.slide) {
			// One row's width, so the old one is clear of the stage as the new one
			// lands: a page turn, with nothing to line up on.
			const run = z.slide * box.width;
			z.play = { ghost: `translateX(${-run}px)`, live: `translateX(${run}px)` };
		} else {
			z.play =
				to && scale !== 1
					? {
							ghost: `translate(${to.cx - dx - scale * z.at.cx}px, ${to.cy - dy - scale * z.at.cy}px) scale(${scale})`,
							live: `translate(${z.at.cx + dx - to.cx / scale}px, ${z.at.cy + dy - to.cy / scale}px) scale(${1 / scale})`
						}
					: { ghost: 'none', live: 'none' };
		}
		requestAnimationFrame(() => {
			if (zoom === z) z.on = true;
		});
		clearTimeout(zoomTimer);
		zoomTimer = setTimeout(() => {
			if (zoom === z) zoom = null;
		}, ZOOM_MS + 80);
	}

	$effect(() => {
		void opened;
		untrack(holdZoom);
	});

	const zoomStyle = $derived.by(() => {
		// Nothing until the change lands: up to then the row is the old one, and
		// it is the picture held over it.
		if (!zoom?.hold) return '';
		const origin = 'transform-origin: 0 0;';
		if (!zoom.on) {
			// Hidden from the instant the change lands, not just once the row has
			// somewhere to move from: it is rebuilt from nothing on every change,
			// and its ground is transparent, so a body still waiting for its
			// texture would show through the picture held over it.
			return `${origin} opacity: 0;${zoom.play ? ` transform: ${zoom.play.live};` : ''}`;
		}
		// A page turn brings the new row on from off the stage, so it needs no
		// fade at all; it is only a zoom, where both rows draw the same object,
		// that has to come up first and be dissolved onto — sharing the fade
		// there would dim the object they are both drawing.
		const fade = zoom.slide ? '' : `, opacity ${ZOOM_IN_MS}ms linear`;
		return `${origin} transition: transform ${ZOOM_MS}ms ${ZOOM_EASE}${fade}; opacity: 1;`;
	});

	const ghostStyle = $derived.by(() => {
		if (!zoom) return '';
		const { box, hold, play, on } = zoom;
		const place = `left: ${hold?.dx ?? 0}px; top: ${hold?.dy ?? 0}px; width: ${box.width}px; height: ${box.height}px;`;
		if (!play || !on) return place;
		// Carried off the stage, the old row needs no fade either.
		const fade = zoom.slide
			? ''
			: `, opacity ${ZOOM_MS - ZOOM_IN_MS}ms linear ${ZOOM_IN_MS}ms; opacity: 0`;
		return `${place} transition: transform ${ZOOM_MS}ms ${ZOOM_EASE}${fade}; transform: ${play.ghost};`;
	});

	// --- the maximized object's own page ---

	/** The panel's focus target, built from the object's bundle. Held while the
	 *  next one resolves: the panel stays mounted and reads the new object into
	 *  the same frame, instead of a fresh one sliding in over the old. The row
	 *  has already cached the bundle, so the swap is near-immediate. */
	// Raw: it is replaced whole, never edited, and a deep proxy would reach into
	// the body's own record — satellite.js writes through its SGP4 record as it
	// propagates, which a reactive proxy refuses mid-render.
	let focusable = $state.raw<CompareFocus | null>(null);
	$effect(() => {
		const id = opened;
		if (!id) {
			focusable = null;
			return;
		}
		let stale = false;
		compareFocusable(id).then((next) => {
			if (!stale) focusable = next;
		});
		return () => {
			stale = true;
		};
	});

	// The panel reads its own focus off the view, so the view has to name the
	// object it is open on — or the group, for a rocket.
	$effect(() => {
		const id = opened;
		if (!id) return;
		const name = resolved[id]?.name ?? '';
		const group = rocketBySlug(id)?.group;
		untrack(() =>
			group
				? appState.setGroup(group, name)
				: appState.setFocus({ type: urlTypeFromId(id), id, name })
		);
	});

	/** The panel is the map's whole drawer, so it is fetched only once a reader
	 *  opens one. */
	let DetailDrawer = $state<typeof import('../../components/detail/DetailDrawer.svelte').default>();
	$effect(() => {
		if (!opened || DetailDrawer) return;
		void import('../../components/detail/DetailDrawer.svelte').then((mod) => {
			DetailDrawer = mod.default;
		});
	});
</script>

<svelte:head>
	<title>{m.compare_page_title()} - {m.page_title()}</title>
</svelte:head>

<svelte:window
	bind:innerWidth
	onkeydown={(e) => {
		if (e.key === 'Escape') menu = null;
	}}
/>

<!-- The panel is fixed to the start edge and would ride over the site nav;
     --detail-top puts it under. -->
<div class="flex h-dvh flex-col overflow-hidden bg-background" style="--detail-top: 3.5rem">
	<SiteNav current="compare" class="shrink-0" />

	<div class="relative flex min-h-0 flex-1">
		{#if opened && !narrow}
			<!-- The room the panel stands in: it is fixed, so the row needs telling. -->
			<div class="w-[var(--detail-panel)] max-w-[90vw] shrink-0"></div>
		{:else if railOpen && !narrow}
			<!-- The comparison: one row per object, largest first, as drawn. -->
			<aside class="flex w-[300px] shrink-0 flex-col border-e border-border bg-card">
				<ScrollArea class="min-h-0 flex-1">
					<div class="flex flex-col gap-4 p-5">
						<div class="flex items-center gap-2">
							<h1 class="flex-1 text-[17px] font-semibold tracking-tight">
								{m.compare_page_title()}
							</h1>
							<span class="text-xs text-muted-foreground"
								>{m.compare_object_count({ count: objects.length })}</span
							>
							<button
								type="button"
								aria-label={m.compare_hide_list()}
								aria-expanded="true"
								onclick={() => (railOpen = false)}
								class="flex size-7 items-center justify-center rounded-lg text-muted-foreground hover:bg-accent hover:text-foreground"
							>
								<ChevronsLeftIcon class="size-4" />
							</button>
						</div>

						<div class="flex flex-col gap-2">
							<span class="text-[11px] font-medium tracking-wider text-muted-foreground uppercase"
								>{m.compare_presets()}</span
							>
							<div class="flex flex-wrap gap-1.5">
								{#each COMPARE_PRESETS as preset (preset.slug)}
									{@const on = presetOn(preset, selected)}
									<button
										type="button"
										aria-pressed={on}
										onclick={() => togglePreset(preset)}
										class="h-7 rounded-lg border px-2.5 text-xs transition-colors {on
											? 'border-primary bg-primary/10 font-medium text-foreground'
											: 'border-border hover:bg-accent'}"
									>
										{preset.label()}
									</button>
								{/each}
							</div>
							<button
								type="button"
								aria-pressed={comparablesOn}
								onclick={toggleComparables}
								class="h-7 self-start rounded-lg border px-2.5 text-xs transition-colors {comparablesOn
									? 'border-primary bg-primary/10 font-medium text-foreground'
									: 'border-border hover:bg-accent'}"
							>
								{m.compare_comparables()}
							</button>
						</div>

						<Popover.Root bind:open={pickerOpen}>
							<Popover.Trigger
								class="flex h-11 items-center justify-center gap-2 rounded-xl border border-dashed border-border bg-accent/40 text-sm font-medium hover:bg-accent"
							>
								<PlusIcon class="size-4" />
								{m.compare_add()}
							</Popover.Trigger>
							<Popover.Content
								side="right"
								align="start"
								sideOffset={10}
								collisionPadding={12}
								class="w-[380px] p-0"
							>
								<ComparePicker chosen={selected} onadd={addHit} />
							</Popover.Content>
						</Popover.Root>

						{#if objects.length}
							<button
								type="button"
								onclick={() => setIds([])}
								class="-mt-2 self-start text-xs text-muted-foreground hover:text-foreground"
								>{m.compare_clear()}</button
							>
						{/if}

						<ul class="flex flex-col border-t border-border">
							{#each listed as object (object.id)}
								<li class="flex h-11 items-center gap-2.5 border-b border-border/60">
									<span class="size-2.5 shrink-0 rounded-full" style="background: {colorOf(object)}"
									></span>
									{#if hasPage(object)}
										<!-- Maximizes it here; its own page is on the context menu. -->
										<a
											href={compareHref(selected, object.id)}
											onclick={(e) => {
												if (isModifiedClick(e)) return;
												e.preventDefault();
												openObject(object.id);
											}}
											class="flex-1 truncate text-[13.5px] font-medium hover:underline"
											>{object.name}</a
										>
									{:else}
										<span class="flex-1 truncate text-[13.5px] font-medium">{object.name}</span>
									{/if}
									<span class="shrink-0 text-xs text-muted-foreground tabular-nums"
										>{sizeText(object)}</span
									>
									<button
										type="button"
										aria-label={m.compare_remove({ name: object.name })}
										onclick={() => remove(object.id)}
										class="flex size-6 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
									>
										<XIcon class="size-3.5" />
									</button>
								</li>
							{/each}
						</ul>
					</div>
				</ScrollArea>
			</aside>
		{/if}

		<!-- The row stands on the stage sheet, and everything over it is inked
		     from the theme: dark it is the sky the map draws, light a bare sheet. -->
		<div
			bind:clientWidth={stageWidth}
			bind:clientHeight={stageHeight}
			role="group"
			aria-label={m.compare_lineup_label()}
			class="relative min-w-0 flex-1 overflow-hidden bg-stage text-foreground"
			onpointerdown={onSwipeStart}
			onpointerup={onSwipeEnd}
			onpointercancel={() => (swipeFrom = null)}
		>
			<!-- Everything the row is made of moves together when it zooms. -->
			<div class="absolute inset-0" style={zoomStyle}>
				{#if bodies.length && stageHeight > LABEL_ROW}
					<!-- The row draws the neighbouring pages too, at its own scale. -->
					<div bind:this={rowBox} class="relative">
						<BodyLineup
							bind:this={row}
							{bodies}
							ariaLabel={m.compare_lineup_label()}
							height={stageHeight - LABEL_ROW}
							pxPerKm={current.scale || undefined}
							boxed
							labels
							ground="transparent"
							spread={false}
							onlayout={(items) => (laid = items)}
							oncontextpick={(id, x, y) => (menu = { id, x, y })}
							onpick={(id) => openObject(id)}
						/>
					</div>
				{:else}
					<p class="flex h-full items-center justify-center text-sm text-muted-foreground">
						{objects.length === 0 && selected.length > 0 ? m.compare_loading() : m.compare_empty()}
					</p>
				{/if}

				{#if ghost}
					<!-- The strip of the page before is the way back to it. -->
					{#if ghostAt}
						<button
							type="button"
							aria-hidden="true"
							tabindex="-1"
							onclick={() => turn(-1)}
							onpointerenter={() => (hot = 'prev')}
							onpointerleave={() => (hot = null)}
							class="absolute inset-y-0 start-0 z-10 flex items-center justify-end pe-1"
							style="width: {Math.max(0, ghostAt.cx + ghostAt.pr)}px"
						>
							<ChevronLeftIcon
								class="size-5 transition-colors {hot === 'prev'
									? 'text-foreground'
									: 'text-muted-foreground'}"
							/>
						</button>
					{/if}
					<!-- On a scrim of the stage: the body behind it is lit. -->
					<button
						type="button"
						onclick={() => turn(-1)}
						onpointerenter={() => (hot = 'prev')}
						onpointerleave={() => (hot = null)}
						aria-label={opened ? m.compare_open({ name: ghost.name }) : m.search_prev_page()}
						class="absolute start-5 z-10 flex h-8 items-center gap-1.5 rounded-lg px-2 text-[11.5px] transition-colors {hot ===
						'prev'
							? 'bg-stage/80 text-foreground'
							: 'bg-stage/55 text-muted-foreground'}"
						style="bottom: {LABEL_ROW + 14}px"
					>
						<ChevronLeftIcon class="size-3.5" />
						<span>{neighbourLabel(ghost, pageIndex, narrow)}</span>
					</button>
				{/if}

				{#if speck && speckAt}
					<!-- A speck is a few pixels across, so the reach for it is the width
				     of the strip it sits in; a limb is reached over its own width. -->
					<button
						type="button"
						aria-hidden="true"
						tabindex="-1"
						onclick={() => turn(1)}
						onpointerenter={() => (hot = 'next')}
						onpointerleave={() => (hot = null)}
						class="absolute inset-y-0 z-10 flex items-center justify-start ps-1"
						style="left: {Math.min(speckAt.cx - speckAt.pr, speckAt.cx - 22)}px; right: 0"
					>
						<ChevronRightIcon
							class="size-5 translate-y-8 transition-colors {hot === 'next'
								? 'text-foreground'
								: 'text-muted-foreground'}"
						/>
					</button>
					{#if !narrow}
						<button
							type="button"
							onclick={() => turn(1)}
							onpointerenter={() => (hot = 'next')}
							onpointerleave={() => (hot = null)}
							aria-label={opened ? m.compare_open({ name: speck.name }) : m.search_next_page()}
							class="absolute end-5 z-10 flex h-8 items-center gap-1.5 rounded-lg px-2 text-[11.5px] transition-colors {hot ===
							'next'
								? 'bg-stage/80 text-foreground'
								: 'bg-stage/55 text-muted-foreground'}"
							style="bottom: {LABEL_ROW + 14}px"
						>
							<span>{neighbourLabel(speck, pageIndex + 2)}</span>
							<ChevronRightIcon class="size-3.5" />
						</button>
					{/if}
				{/if}

				{#if scaleBar}
					<!-- Bottom centre, between the page links; a phone has no room there.
					     On its own scrim: a maximized body is drawn under it. -->
					<div
						class="pointer-events-none absolute flex flex-col gap-1 rounded-md bg-stage/70 px-1.5 py-1 {narrow
							? 'start-5 top-5 items-start'
							: 'left-1/2 -translate-x-1/2 items-center'}"
						style={narrow ? '' : `bottom: ${LABEL_ROW + 14}px`}
					>
						<div
							class="h-[7px] border-x border-b border-muted-foreground"
							style="width: {scaleBar.px}px"
						></div>
						<span class="text-[11px] text-muted-foreground tabular-nums">{scaleBar.label}</span>
					</div>
				{/if}

				{#if comparableBody && comparableFits}
					<!-- Not a member of the comparison but a reference beside it, on the
					     row's own scale. Right-hand side, where the row leaves the most
					     room, clear of the page link below it. The box is cut to the
					     drawing: most of these are long and low, a few are towers, and
					     either way the rest would be air. -->
					<div
						class="pointer-events-none absolute end-5"
						style="bottom: {LABEL_ROW + 54}px; width: {Math.max(
							96,
							comparableBox + 2 * SIDE_PAD
						)}px"
					>
						<BodyLineup
							bodies={[comparableBody]}
							ariaLabel={comparableBody.name}
							height={comparableTall}
							{pxPerKm}
							ground="transparent"
							spread={false}
						/>
						<span class="text-center text-[11px] leading-tight text-muted-foreground">
							{comparableBody.name} ·
							<span class="tabular-nums">{comparableSize}</span>
						</span>
					</div>
				{/if}

				{#if pages.length > 1 && narrow && !opened}
					<!-- The phone has no next-page link, only the strip, so it counts pages. -->
					<div
						role="group"
						aria-label={m.compare_pages_label({ n: pageIndex + 1, total: pages.length })}
						class="pointer-events-none absolute left-1/2 flex -translate-x-1/2 gap-1.5"
						style="bottom: {LABEL_ROW + 16}px"
					>
						{#each pages.map((_, i) => i) as i (i)}
							<span
								class="size-[7px] rounded-full {i === pageIndex
									? 'bg-foreground/85'
									: 'bg-foreground/30'}"
							></span>
						{/each}
					</div>
				{/if}
			</div>

			{#if zoom}
				<!-- The row as it was, over the row as it is, on its way to it. -->
				<img
					src={zoom.src}
					alt=""
					aria-hidden="true"
					class="pointer-events-none absolute z-20 max-w-none origin-top-left"
					style={ghostStyle}
				/>
			{/if}

			<!-- Same corner as the map's, crediting what this page draws. -->
			<div class="absolute end-0 z-10" style="bottom: var(--safe-bottom)">
				<CompareCreditBar bodies={comparableBody ? [...bodies, comparableBody] : bodies} />
			</div>

			{#if !railOpen && !narrow && !opened}
				<button
					type="button"
					aria-label={m.compare_show_list()}
					aria-expanded="false"
					onclick={() => (railOpen = true)}
					class="absolute start-5 top-5 flex size-11 items-center justify-center rounded-xl border border-border bg-card/70 text-foreground backdrop-blur-sm hover:bg-card"
				>
					<MenuIcon class="size-[18px]" />
				</button>
			{/if}
		</div>

		{#if narrow}
			<!-- No drawer on a phone: the row keeps the screen, and the set is
			     changed from the one control over it. It sits at the top because
			     the bottom corner is where the page strip and the credit are, and
			     above the next-page strip, which reaches the same corner. -->
			<Popover.Root bind:open={pickerOpen}>
				<Popover.Trigger
					aria-label={m.compare_add()}
					class="absolute end-3 top-3 z-20 flex size-11 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-lg"
				>
					<PlusIcon class="size-5" />
				</Popover.Trigger>
				<Popover.Content
					side="bottom"
					align="end"
					sideOffset={8}
					collisionPadding={12}
					class="w-[330px] p-0"
				>
					<ComparePicker chosen={selected} onadd={addHit} onpreset={togglePreset} />
				</Popover.Content>
			</Popover.Root>
		{/if}

		{#if opened && !(focusable && DetailDrawer)}
			<!-- The panel's own frame while its chunk and payload arrive, so the
			     room it stands in is never left bare. -->
			<DrawerSkeleton
				kind={opened && rocketBySlug(opened) ? 'group' : 'body'}
				title={(opened && resolved[opened]?.name) || ''}
				onClose={() => openObject(null)}
			/>
		{/if}

		{#if focusable && DetailDrawer}
			<!-- The panel's tooltips share one group, the way they do on the map. -->
			<Tooltip.Provider delayDuration={300}>
				<!-- The placeholder frame always stands here first, so the sheet takes
				     its place rather than sliding in over it. -->
				<DetailDrawer
					{focusable}
					{clock}
					inPlace={true}
					mapHref={focusable.kind === 'group'
						? groupHref(focusable.slug, (opened && resolved[opened]?.name) || '')
						: bodyHref(focusable.body.data.id, focusable.body.data.name ?? '')}
					onClose={() => openObject(null)}
				/>
			</Tooltip.Provider>
		{/if}

		{#if menu && menuObject}
			<!-- Right click on a body: go to it, or drop it. -->
			<div
				class="fixed z-50 flex w-52 flex-col rounded-xl border border-border bg-popover p-1.5 shadow-xl"
				style="left: {Math.min(menu.x, innerWidth - 220)}px; top: {menu.y}px"
			>
				{#if hasPage(menuObject)}
					<a
						href={pageHref(menuObject)}
						class="flex h-9 items-center gap-2.5 rounded-lg px-2.5 text-[13px] hover:bg-accent"
					>
						<ExternalLinkIcon class="size-3.5" />
						{m.compare_open({ name: menuObject.name })}
					</a>
				{/if}
				<button
					type="button"
					onclick={() => remove(menuObject.id)}
					class="flex h-9 items-center gap-2.5 rounded-lg px-2.5 text-start text-[13px] hover:bg-accent"
				>
					<XIcon class="size-3.5" />
					{m.compare_remove_short()}
				</button>
			</div>
			<!-- One click anywhere else closes it. -->
			<button
				type="button"
				tabindex="-1"
				aria-label={m.close()}
				onclick={() => (menu = null)}
				class="fixed inset-0 z-40 cursor-default"
			></button>
		{/if}
	</div>
</div>
