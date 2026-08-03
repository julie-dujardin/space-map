<script lang="ts">
	import { getContext, untrack } from 'svelte';
	import ChevronRightIcon from '@lucide/svelte/icons/chevron-right';
	import * as m from '$lib/paraglide/messages.js';
	import type { LocalizedRingFeature, RingFeature } from '$lib/fetch/objects/object-data';
	import type { PositionedBody } from '$lib/types/objects';
	import { ObjectType } from '$lib/types/objects';
	import { chebyshevPositionKm } from '$lib/fetch/position/chebyshev/propagate';
	import type { SimClock } from '$lib/scene/state/clock.svelte';
	import {
		buildRows,
		childSummary,
		kindSummary,
		formatOpticalDepth,
		opacity,
		rootSlugs,
		tauOpacity,
		type RingRow
	} from '$lib/rings/catalog';
	import { loadRingStrips, type RingStripProfile } from '$lib/rings/strip';
	import { formatNumber } from '$lib/format/quantities';
	import { AU_KM } from '$lib/math/units';
	import { TYPE_COLOR_MOON } from '$lib/constants';
	import type { AppState } from '$lib/state/app-state.svelte';
	import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
	import type { FocusObject } from '$lib/state/focusable';
	import { applyFocus, serializeUrl, urlTypeFromId } from '$lib/state/url';
	import { resolveBodyColor } from '$lib/utils';
	import * as Tooltip from '$lib/components/ui/tooltip/index.js';
	import ObjectDescription from './ObjectDescription.svelte';

	interface Props {
		features: Record<string, RingFeature>;
		localized?: Record<string, LocalizedRingFeature>;
		/** The "Rings of X" article — shown until a feature is picked. */
		system?: LocalizedRingFeature;
		/** Host radius, for the R-planet axis. Falls back to a km axis. */
		bodyRadiusKm?: number;
		/** Host and its barycentre, for the rendered ring strips and the moons
		 *  of the system. Without them the chart draws the catalogue alone. */
		bodyId?: string;
		systemId?: string;
		/** Read once per level, to sample the moons' ephemeris — never tracked,
		 *  or the chart would rebuild on every frame of sim time. */
		clock?: SimClock;
	}

	let { features, localized, system, bodyRadiusKm, bodyId, systemId, clock }: Props = $props();

	const appState = getContext<AppState | undefined>('appState');
	const focusObject = getContext<FocusObject | undefined>('focusObject');
	const ctx = getContext<ContextManager | undefined>('ctx');

	function moonHref(moon: { name: string; id?: string }): string | undefined {
		if (!appState || !moon.id) return undefined;
		return serializeUrl(
			applyFocus(appState.view, {
				type: urlTypeFromId(moon.id),
				id: moon.id,
				name: moon.name
			})
		);
	}

	function focusMoon(e: MouseEvent, moon: { name: string; id?: string }) {
		if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
		if (!focusObject || !moon.id) return;
		e.preventDefault();
		focusObject(moon.id, moon.name);
	}

	/** Deep link to a level of the catalogue; null is the system itself. A
	 *  cluster gets none — the URL has no name for a row the scale invented. */
	function ringHref(entry: Level | null): string | undefined {
		if (!appState || (entry && !('slug' in entry))) return undefined;
		return serializeUrl({ ...appState.view, tab: 'rings', ring: entry ? entry.slug : null });
	}

	/** Drill in place on a plain click, leaving modified ones to the browser —
	 *  the href is a real page, so ⌘-click opens the section in a new tab. */
	function openLevel(e: MouseEvent, next: Level[]) {
		if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
		e.preventDefault();
		path = next;
	}

	const CRUMB_CLASS = 'text-muted-foreground hover:text-foreground';
	let systemHref = $derived(ringHref(null));

	// The gutter holds the axis ticks, right-aligned against the strip. Its
	// width follows the ticks a level actually draws: a fixed one wide enough
	// for "4,780,000" leaves a band of nothing beside "8.75", and every pixel
	// here is one the ring names lose.
	const TICK_CHAR = 5.4;
	const TICK_PAD = 10;
	const GUTTER_MIN = 24;
	const GUTTER_MAX = 58;
	/** A label row: the width mark's 10 px monospace, and the flex gap. */
	const MARK_CHAR = 6.6;
	const ROW_GAP = 8;
	const STRIP_WIDTH = 46;
	const LEADER_WIDTH = 22;
	/** Moon column: how far sideways a knot of moons may spread before dots
	 *  start touching, the clear space each one keeps, and the size range
	 *  mapped across the radii a ring system's moons actually span. */
	const MOON_DOT_COLUMNS = 4;
	const MOON_DOT_CLEARANCE = 3;
	const DOT_MIN = 4;
	const DOT_MAX = 12;
	const DOT_MIN_KM = 0.3;
	const DOT_MAX_KM = 300;
	/** Points per orbit when averaging a moon's distance from the planet. */
	const MEAN_SAMPLES = 16;
	const LABEL_GAP = 22;
	// One scale for the whole axis — a pixel is the same number of decades (or
	// kilometres) everywhere. What gives instead are the two things that cost
	// nothing to give: empty stretches are cut out and marked with a break, and
	// rings too close to label separately fold into a group row you can open.
	// Two screens at 1080p is fine; the panel scrolls.
	const MAX_HEIGHT = 2000;
	// Floor for a level with only a couple of rows, where label spacing alone
	// would leave the strip too short to read.
	const MIN_HEIGHT = 260;
	// A label may be nudged this far off its own band before its ring is folded
	// into a group instead. A few pixels of lean is invisible; a group is a real
	// loss of detail, so it is the last resort rather than the first.
	const LABEL_SLACK = 12;
	const BREAK_HEIGHT = 24;
	// Only excise a void that would otherwise waste more than this much height.
	// High enough that a break has to buy back a real stretch of chart: inside
	// the Cassini Division every unnamed plateau between two gaps is a few
	// hundred kilometres, and cutting each one turned a 3,000 km window into a
	// ladder of break markers.
	const MIN_VOID = 240;
	// Below this ratio between the innermost and outermost radius the axis is
	// linear; above it, logarithmic.
	const LOG_THRESHOLD = 8;

	let rows = $derived(buildRows(features));

	/** A row on screen: one feature, or a run of them too close to separate. */
	type Level = { slug: string } | { cluster: string[] };
	/** Drill path from the top-level rings; empty is the whole system. */
	let path = $state<Level[]>([]);

	// A path into features that vanish (body switched under us) would strand the
	// panel on an empty list.
	$effect(() => {
		const alive = path.every((level) =>
			'slug' in level ? rows.has(level.slug) : level.cluster.every((s) => rows.has(s))
		);
		if (!alive) path = [];
	});

	/** The deepest feature on the path — the section the URL names. A cluster is
	 *  an artefact of the scale the chart happens to be drawn at, not a feature
	 *  anyone can link to, so a path ending in one is shared as the feature
	 *  enclosing it. */
	let pathSlug = $derived.by(() => {
		for (let i = path.length - 1; i >= 0; i--) {
			const entry = path[i];
			if ('slug' in entry) return entry.slug;
		}
		return null;
	});

	/** The path that lands on a feature: its chain of parents, outermost first.
	 *  Empty for a slug this body's catalogue doesn't hold. */
	function pathTo(slug: string | null): Level[] {
		const levels: Level[] = [];
		// Bounded against a catalogue whose parents cycle, which would otherwise
		// hang the panel rather than just draw the wrong breadcrumb.
		for (
			let at = slug;
			at && levels.length <= rows.size;
			at = rows.get(at)!.feature.parent ?? null
		) {
			if (!rows.has(at)) {
				console.debug(`Ring panel: ?ring=${at} names no feature of this body, ignored`);
				return [];
			}
			levels.unshift({ slug: at });
		}
		return levels;
	}

	// The two directions of the deep link. `rows` is read so a link that arrives
	// before the catalogue does still opens once it has.
	$effect(() => {
		const slug = appState?.view.ring ?? null;
		void rows;
		untrack(() => {
			if (slug !== pathSlug) path = pathTo(slug);
		});
	});
	$effect(() => {
		const slug = pathSlug;
		untrack(() => appState?.setRing(slug));
	});

	let level = $derived(path[path.length - 1]);
	/** The feature drilled into, if the current level is one (not a group). */
	let drilledRow = $derived(level && 'slug' in level ? rows.get(level.slug) : undefined);

	let visible = $derived.by(() => {
		const slugs = !level
			? rootSlugs(rows)
			: 'slug' in level
				? (rows.get(level.slug)?.children ?? [])
				: level.cluster;
		// Ordered by mid radius, because that is where each label points. Sorting
		// by inner edge instead would list Saturn's E ring before the Methone,
		// Anthe and Pallene rings its span swallows, and its label — pinned to a
		// middle beyond all three — would have to cross theirs to get there.
		return [...slugs].sort((a, b) => mid(rows.get(a)!) - mid(rows.get(b)!));
	});

	function mid(row: RingRow): number {
		return (row.inner + row.outer) / 2;
	}

	// The scene loads a system's moons in batches; without this the column would
	// hold whatever had arrived when the panel first drew.
	let bodiesVersion = $state(0);
	$effect(() => ctx?.bodies.onBodiesAdded(() => bodiesVersion++));

	/** Every moon of the host system with its mean orbital radius, whatever the
	 *  catalogue does or doesn't say about it.
	 *
	 *  Deliberately not the moons the catalogue names: that list is a handful of
	 *  shepherds and resonance partners, and the chart would silently omit
	 *  everything else orbiting among the rings — S/2009 S 2 and the rest of
	 *  Saturn's moonlets. What the radial axis covers is the only filter. */
	let systemMoons = $derived.by(() => {
		// Read so a later batch of bodies re-runs this.
		void bodiesVersion;
		const ids = systemId ? ctx?.bodies.getChildren(systemId) : undefined;
		if (!ids) return [];
		const moons = [];
		for (const id of ids) {
			const body = ctx?.getBody(id);
			if (!body || body.data.objectType !== ObjectType.MOON) continue;
			const radius = meanRadiusKm(body);
			if (radius !== undefined) moons.push({ id, name: body.data.name ?? id, radius, body });
		}
		return moons;
	});

	function label(slug: string): string {
		return localized?.[slug]?.name ?? rows.get(slug)?.feature.name ?? slug;
	}

	function levelLabel(entry: Level): string {
		return 'slug' in entry
			? label(entry.slug)
			: `${label(entry.cluster[0])}–${label(entry.cluster[entry.cluster.length - 1])}`;
	}

	let domain = $derived.by(() => {
		// The feature drilled into spans the window even where none of its
		// children do: opening the Huygens Gap on the ringlet inside it hides
		// most of the gap you asked to see.
		const spans = visible.map((slug) => rows.get(slug)!);
		if (drilledRow) spans.push(drilledRow);
		if (!spans.length) return { min: 1, max: 2, log: false };
		const min = Math.min(...spans.map((r) => r.inner));
		const max = Math.max(...spans.map((r) => r.outer));
		const log = max / Math.max(min, 1) > LOG_THRESHOLD;
		// Multiplicative padding on a log axis: an additive margin against
		// Saturn's 12-million-km Phoebe ring would push the inner edge past zero.
		// Equal bounds (a lone radius-only feature) would collapse the scale.
		if (log) return { min: min / 1.02, max: max * 1.02, log };
		const pad = max > min ? (max - min) * 0.02 : Math.max(max * 0.02, 1);
		return { min: Math.max(min - pad, 0), max: max + pad, log };
	});

	/** Axis coordinate of a radius: decades on a log axis, kilometres on a
	 *  linear one. Pixels are a constant multiple of this. */
	function pos(radius: number): number {
		return domain.log ? Math.log10(Math.max(radius, 1)) : radius;
	}

	/** The plotted axis: the runs that hold rings, with the voids between them
	 *  cut out. Everything inside a run is drawn at one true scale; each cut is
	 *  a marked break, so the jump is stated rather than hidden. */
	let axis = $derived.by(() => {
		const lo = pos(domain.min);
		const hi = pos(domain.max);
		const bands = visible
			.map((slug) => rows.get(slug)!)
			// The drilled feature is material of its own, not a void between its
			// children: without it the stretch of the Cassini Division either side
			// of the Huygens Gap's ringlet would be cut out from under it.
			.concat(drilledRow ? [drilledRow] : [])
			.map((row) => [pos(row.inner), pos(row.outer)] as [number, number])
			// A moon's own orbit anchors the axis as much as a ring does: Titan
			// sits in the empty million kilometres between Saturn's E ring and
			// its Phoebe ring, and cutting that stretch away would drop the dot
			// or — worse — leave it pinned to the edge of the break.
			.concat(
				systemMoons
					.map((moon) => pos(moon.radius))
					.filter((p) => p >= lo && p <= hi)
					.map((p) => [p, p] as [number, number])
			)
			.sort((a, b) => a[0] - b[0]);
		if (!bands.length) return { runs: [{ from: lo, to: hi, top: 0 }], scale: 1, height: 1 };

		// The scale that would separate every label, and the scale that fits the
		// height ceiling. Whichever is smaller wins; clustering absorbs the rest.
		// The tightest pair of neighbours sets it: whatever separates them
		// separates everyone. Where that exceeds the height ceiling the slack
		// below absorbs the difference, and grouping catches what it cannot.
		const anchors = visible.map((slug) => pos(mid(rows.get(slug)!)));
		let ideal = 0;
		for (let i = 0; i < anchors.length - 1; i++) {
			const step = anchors[i + 1] - anchors[i];
			if (step > 0) ideal = Math.max(ideal, LABEL_GAP / step);
		}

		// Which voids to cut depends on the scale, and the scale depends on how
		// much is left after cutting — settle it by iterating.
		let scale = ideal || MAX_HEIGHT / (hi - lo || 1);
		let runs: { from: number; to: number; top: number }[] = [];
		for (let pass = 0; pass < 4; pass++) {
			runs = [{ from: lo, to: lo, top: 0 }];
			for (const [from, to] of bands) {
				const current = runs[runs.length - 1];
				if ((from - current.to) * scale > MIN_VOID) runs.push({ from, to, top: 0 });
				else current.to = Math.max(current.to, to);
			}
			const last = runs[runs.length - 1];
			if ((hi - last.to) * scale <= MIN_VOID) last.to = hi;
			const plotted = runs.reduce((sum, run) => sum + (run.to - run.from), 0) || 1;
			const breaks = (runs.length - 1) * BREAK_HEIGHT;
			const fits = (MAX_HEIGHT - breaks) / plotted;
			// Separating two labels can need as little as 20 px, which would draw
			// the A ring's two gaps as a smear. The scale is true either way, so
			// the floor costs nothing but pixels.
			const floor = (MIN_HEIGHT - breaks) / plotted;
			// No `ideal` means no pair of labels to separate — every row shares a
			// radius (Neptune's Adams arcs) — so the floor is the whole
			// constraint. Falling back to the ceiling would stretch a 16 km
			// window over two screens.
			const next = Math.min(Math.max(ideal || floor, floor), fits);
			if (Math.abs(next - scale) < 0.01 * scale) break;
			scale = next;
		}

		let top = 0;
		for (const run of runs) {
			run.top = top;
			top += (run.to - run.from) * scale + BREAK_HEIGHT;
		}
		return { runs, scale, height: Math.max(top - BREAK_HEIGHT, LABEL_GAP) };
	});

	let chartHeight = $derived(axis.height);

	function y(radius: number): number {
		const { runs, scale } = axis;
		const p = pos(radius);
		let run = runs[0];
		for (const candidate of runs) if (p >= candidate.from) run = candidate;
		return run.top + (Math.min(Math.max(p, run.from), run.to) - run.from) * scale;
	}

	/** Rows as drawn: neighbours whose labels cannot clear each other at this
	 *  scale fold into one group, which opens into its own view. */
	let placed = $derived.by(() => {
		let clusters: string[][] = [];
		for (const slug of visible) {
			const previous = clusters[clusters.length - 1];
			const anchor = y(mid(rows.get(slug)!));
			const last = previous && y(mid(rows.get(previous[previous.length - 1])!));
			if (previous && anchor - last! < LABEL_GAP - LABEL_SLACK) previous.push(slug);
			else clusters.push([slug]);
		}
		// A group holding the whole level opens onto itself — Neptune's five
		// Adams arcs share one radius and differ only in longitude, so no scale
		// ever separates them. List them instead; the labels still stack apart
		// below, they just no longer point at distinct bands.
		if (clusters.length === 1 && clusters[0].length > 1)
			clusters = clusters[0].map((slug) => [slug]);
		let ceiling = -Infinity;
		const items = clusters.map((group) => {
			const anchor =
				group.length === 1
					? y(mid(rows.get(group[0])!))
					: (y(mid(rows.get(group[0])!)) + y(mid(rows.get(group[group.length - 1])!))) / 2;
			const top = Math.max(anchor, ceiling + LABEL_GAP);
			ceiling = top;
			return { group, bandY: anchor, top };
		});
		let floor = chartHeight;
		for (const item of [...items].reverse()) {
			item.top = Math.min(item.top, floor);
			floor = item.top - LABEL_GAP;
		}
		return items;
	});

	/** Radius at a chart pixel — the inverse of `y`. NaN inside a break, where
	 *  the axis has no radius to give. */
	function radiusAt(yPx: number): number {
		const { runs, scale } = axis;
		let run = runs[0];
		for (const candidate of runs) if (yPx >= candidate.top) run = candidate;
		const p = run.from + (yPx - run.top) / scale;
		// Half a chart pixel of tolerance: the far edge of the run's last row
		// lands just past `to`, and rejecting it would drop whatever sits
		// against the break — on Uranus that is the ε ring.
		if ((p - run.to) * scale > 0.5) return NaN;
		return domain.log ? 10 ** Math.min(p, run.to) : Math.min(p, run.to);
	}

	// Raw: the deep proxy would wrap the profiles' typed arrays and hand back
	// empty ones, and nothing here mutates a loaded profile in place.
	let strips = $state.raw<RingStripProfile[]>([]);
	$effect(() => {
		const body = bodyId;
		strips = [];
		if (!body) return;
		let live = true;
		loadRingStrips(body).then((loaded) => {
			if (live) strips = loaded;
		});
		return () => {
			live = false;
		};
	});

	// Two device pixels per chart pixel: the strip resolves features far finer
	// than the chart is tall (13,177 samples across Saturn's main rings), and
	// the extra row keeps a ringlet from disappearing between samples.
	const STRIP_OVERSAMPLE = 2;
	/** Device rows a feature gets even when it is thinner than one. */
	const MIN_MARK = 2;

	/** The strip column as a picture: the rendered ring profiles where a bundle
	 *  covers the radius, the catalogue's optical depths everywhere else.
	 *
	 *  One image rather than a rect per feature so both sources land on the
	 *  same pixels — a band drawn under a profile would show through it. */
	let stripImage = $derived.by(() => {
		if (typeof document === 'undefined') return null;
		const height = Math.max(1, Math.round(chartHeight * STRIP_OVERSAMPLE));
		const canvas = document.createElement('canvas');
		canvas.width = 1;
		canvas.height = height;
		const ctx = canvas.getContext('2d');
		if (!ctx) return null;
		const image = ctx.createImageData(1, height);
		const bands = visible
			.map((slug) => rows.get(slug)!)
			// The drilled feature paints the radii its children leave bare.
			.concat(drilledRow ? [drilledRow] : [])
			// Narrowest last: at a radius covered by both the E ring and the
			// Pallene ring inside it, the specific feature is the informative one.
			.sort((a, b) => b.outer - b.inner - (a.outer - a.inner));
		for (let row = 0; row < height; row++) {
			const from = radiusAt(row / STRIP_OVERSAMPLE);
			const to = radiusAt((row + 1) / STRIP_OVERSAMPLE);
			if (Number.isNaN(from) || Number.isNaN(to)) continue;
			const [lo, hi] = from <= to ? [from, to] : [to, from];
			const sample = sampleStrips(lo, hi);
			let red = 241;
			let green = 245;
			let blue = 249;
			let alpha = 0;
			if (sample) {
				[red, green, blue] = sample.rgb;
				alpha = sample.alpha;
			} else {
				const mid = (lo + hi) / 2;
				for (const band of bands)
					if (mid >= band.inner && mid <= band.outer) alpha = opacity(band.feature);
			}
			image.data[row * 4] = red;
			image.data[row * 4 + 1] = green;
			image.data[row * 4 + 2] = blue;
			image.data[row * 4 + 3] = Math.round(alpha * 255);
		}
		// Uranus' ε ring is 58 km of an 80,000 km bundle: the box filter above
		// averages it into the empty space around it and the row's leader line
		// would point at nothing. The catalogue knows every named feature's
		// optical depth, so each one keeps a mark of its own at minimum.
		for (const band of bands) {
			const top = y(band.inner) * STRIP_OVERSAMPLE;
			const bottom = y(band.outer) * STRIP_OVERSAMPLE;
			if (bottom - top >= MIN_MARK) continue;
			const alpha = Math.round(opacity(band.feature) * 255);
			const first = Math.max(
				0,
				Math.min(height - MIN_MARK, Math.round((top + bottom - MIN_MARK) / 2))
			);
			for (let row = first; row < first + MIN_MARK; row++) {
				const at = row * 4;
				if (image.data[at + 3] >= alpha) continue;
				// Only a row the profile never reached needs a colour of its own.
				if (!image.data[at + 3]) {
					image.data[at] = 241;
					image.data[at + 1] = 245;
					image.data[at + 2] = 249;
				}
				image.data[at + 3] = alpha;
			}
		}
		ctx.putImageData(image, 0, 0);
		return canvas.toDataURL();
	});

	/** The profile across a radius interval, since one chart pixel can swallow
	 *  hundreds of samples. The densest sample wins rather than the mean:
	 *  Uranus' ε ring is a dozen samples of τ ≈ 1 among a hundred of dust, and
	 *  an average would erase the ring the row points at. Null where no bundle
	 *  covers the interval. */
	function sampleStrips(
		lo: number,
		hi: number
	): { rgb: [number, number, number]; alpha: number } | null {
		let covered = false;
		let tau = -1;
		let red = 0;
		let green = 0;
		let blue = 0;
		for (const profile of strips) {
			const n = profile.tau.length;
			const perKm = (n - 1) / (profile.outer - profile.inner);
			const first = Math.round((Math.max(lo, profile.inner) - profile.inner) * perKm);
			const last = Math.round((Math.min(hi, profile.outer) - profile.inner) * perKm);
			if (last < first || first >= n || last < 0) continue;
			covered = true;
			for (let i = Math.max(0, first); i <= Math.min(n - 1, last); i++) {
				const sample = Number.isFinite(profile.tau[i]) ? profile.tau[i] : 10;
				if (sample <= tau) continue;
				tau = sample;
				red = profile.rgb[i * 3];
				green = profile.rgb[i * 3 + 1];
				blue = profile.rgb[i * 3 + 2];
			}
		}
		if (!covered) return null;
		return {
			rgb: [red, green, blue],
			alpha: tauOpacity(tau)
		};
	}

	/** The moons the chart can place, one dot each down the left edge **at the
	 *  moon's own orbit** — never at the feature that names it, since a gap is
	 *  usually named for the moon whose resonance clears it rather than one
	 *  inside it. A moon orbiting outside the level's window has nowhere honest
	 *  to go and is left out; that is the only filter on the column. */
	let moonSet = $derived.by(() => {
		const dots = [];
		let offChart = 0;
		for (const moon of systemMoons) {
			const at = plotted(moon.radius);
			if (at === null) {
				offChart++;
				continue;
			}
			dots.push({
				name: moon.name,
				id: moon.id,
				color: moonColor(moon.body),
				size: moonSize(moon.body),
				bandY: at
			});
		}
		return { dots, offChart };
	});

	$effect(() => {
		if (moonSet.offChart)
			console.debug(
				`Ring panel: ${moonSet.offChart} of ${systemMoons.length} loaded moons orbit outside this window, no dot drawn`
			);
	});

	/** The column as drawn: every dot at its own radius, moving sideways rather
	 *  than up or down when they collide. A dot's height is the one thing it
	 *  says — Tethys and its two trojans share an orbit to within a few hundred
	 *  kilometres, and nudging them apart vertically would draw three different
	 *  orbits with only the innermost one right.
	 *
	 *  Left-most free column wins, so a lone dot after a knot comes back to the
	 *  first column and the knot itself reads outward in radius order. */
	let moonDots = $derived.by(() => {
		// Where each column's last dot ends, plus the clearance the next one owes.
		const bottoms: number[] = [];
		const placed = moonSet.dots
			.slice()
			.sort((a, b) => a.bandY - b.bandY)
			.map((dot) => {
				let column = bottoms.findIndex((bottom) => bottom <= dot.bandY - dot.size / 2);
				// Past the cap the emptiest column takes it and the two dots touch.
				// Saturn's Inuit group is nineteen sub-10 km moons inside one
				// stretch of the Phoebe ring; laying them all out side by side
				// would spend a fifth of the drawer on moonlets nobody hovers.
				if (column < 0)
					column =
						bottoms.length < MOON_DOT_COLUMNS
							? bottoms.length
							: bottoms.indexOf(Math.min(...bottoms));
				bottoms[column] = dot.bandY + dot.size / 2 + MOON_DOT_CLEARANCE;
				return { ...dot, top: dot.bandY, column };
			});

		// Each column is only as wide as its own widest dot: a knot of moonlets
		// costs five pixels a column, not the twelve Titan needs. They fill from
		// the left, so a lone dot sits against the panel edge and only a knot
		// reaches towards the axis.
		const widths: number[] = [];
		for (const dot of placed) widths[dot.column] = Math.max(widths[dot.column] ?? 0, dot.size);
		const lefts: number[] = [];
		let width = 0;
		for (const [column, size] of widths.entries()) {
			lefts[column] = width;
			width += size + MOON_DOT_CLEARANCE;
		}
		width = Math.max(width - MOON_DOT_CLEARANCE, 0);
		return {
			width,
			dots: placed.map((dot) => ({
				...dot,
				left: lefts[dot.column] + (widths[dot.column] - dot.size) / 2
			}))
		};
	});

	/** Mean orbital radius of a moon in km: its distance from the planet
	 *  averaged over one orbit of the ephemeris the scene propagates.
	 *
	 *  Averaged rather than instantaneous because an eccentric moon would
	 *  otherwise wander — Titan by 35,000 km, Phoebe by two million — and a dot
	 *  that moves with the clock is a position, not a place in the ring system.
	 *
	 *  Sampled rather than taken from the semi-major axis because the fitted
	 *  `a` these moons carry is a mean-element fit against an oblate planet and
	 *  runs about a thousand kilometres long this close in: nothing at system
	 *  scale, everything inside the A ring, where it lands Pan outside the gap
	 *  it clears. Both bodies are sampled against the same barycentre, so the
	 *  difference is planet-centred and the barycentre's own wobble drops out.
	 *
	 *  Moons the Chebyshev export doesn't carry fall to the elements below, and
	 *  that is not a lesser answer: the scene propagates those moons from the
	 *  same elements (`update-positions.ts` branches on the same `chebStore.has`),
	 *  and two-body Kepler holds distance-to-parent well over time. Gate on
	 *  `has` so those moons skip a sampling loop that cannot succeed. */
	function meanRadiusKm(moon: PositionedBody): number | undefined {
		const store = ctx?.chebStore;
		const period = moon.data.n ? 360 / Math.abs(moon.data.n) : 0;
		if (store?.has(moon.data.id) && bodyId && period > 0) {
			// Whatever the clock reads when the level changes; a mean over one
			// orbit is the same wherever it starts, so this must not re-derive
			// the whole chart every frame.
			const from = untrack(() => clock?.jd ?? 0);
			let sum = 0;
			let count = 0;
			for (let i = 0; i < MEAN_SAMPLES; i++) {
				const jd = from + (period * i) / MEAN_SAMPLES;
				const satellite = store.body(moon.data.id, jd);
				const host = store.body(bodyId, jd);
				if (!satellite || !host) continue;
				const s = chebyshevPositionKm(satellite, jd);
				const h = chebyshevPositionKm(host, jd);
				if (!s || !h) continue;
				sum += Math.hypot(s[0] - h[0], s[1] - h[1], s[2] - h[2]);
				count++;
			}
			// Half an orbit of samples is not a mean: the outer irregulars take
			// years and the store holds weeks, so a partial window would report
			// wherever Phoebe happens to be rather than where it orbits.
			if (count === MEAN_SAMPLES) return sum / count;
		}
		// The orbit's own time-averaged radius.
		const { a, e } = moon.data;
		return a ? a * AU_KM * (1 + (e * e) / 2) : undefined;
	}

	/** Chart y for a radius, or null where the axis doesn't plot it: outside
	 *  the window, or inside a void the axis cut out. Unlike `y` this refuses
	 *  to clamp — a dot pinned to the edge of a break would read as a position. */
	function plotted(radius: number): number | null {
		const p = pos(radius);
		for (const run of axis.runs)
			if (p >= run.from && p <= run.to) return run.top + (p - run.from) * axis.scale;
		return null;
	}

	/** The moon's own tint, or the generic one — most moonlets among the rings
	 *  are too small to have a colour of their own. */
	function moonColor(moon: PositionedBody): string {
		return resolveBodyColor(moon.data) || TYPE_COLOR_MOON;
	}

	/** Dot size from the moon's real radius, logarithmic and clamped: these run
	 *  from a 300 m moonlet to Titan, so a linear map would draw everything
	 *  under Enceladus as the same speck. An unmeasured moon draws smallest —
	 *  every one of them is a recent faint discovery, and a middling dot would
	 *  put a kilometre-wide moonlet on a par with Pan. */
	function moonSize(moon: PositionedBody): number {
		const km = moon.data.radiusKm;
		if (!km || km <= 0) return DOT_MIN;
		const decades = Math.log10(km / DOT_MIN_KM) / Math.log10(DOT_MAX_KM / DOT_MIN_KM);
		return DOT_MIN + (DOT_MAX - DOT_MIN) * Math.min(1, Math.max(0, decades));
	}

	// A drilled-in window spans a few hundredths of a planetary radius, where
	// every tick would read "1.97"; kilometres are the legible unit there.
	let axisInRadii = $derived(!!bodyRadiusKm && (domain.max - domain.min) / bodyRadiusKm > 0.5);
	let axisUnit = $derived(axisInRadii ? bodyRadiusKm! : 1);

	/** Each plotted run is labelled at both ends, so a break reads as the jump
	 *  it is rather than as a stretch of nothing. */
	let axisTicks = $derived.by(() =>
		axis.runs.flatMap((run) => {
			const height = (run.to - run.from) * axis.scale;
			const radius = (p: number) => (domain.log ? 10 ** p : p);
			const ends = [{ y: run.top, p: run.from }];
			if (height > LABEL_GAP) ends.push({ y: run.top + height, p: run.to });
			return ends.map((end) => ({
				y: end.y,
				text: formatNumber(radius(end.p) / axisUnit)
			}));
		})
	);

	let axisGutter = $derived(
		Math.min(
			GUTTER_MAX,
			Math.max(
				GUTTER_MIN,
				Math.max(0, ...axisTicks.map((t) => t.text.length)) * TICK_CHAR + TICK_PAD
			)
		)
	);
	/** Where a row's extent bracket stands: just off the strip, with the leader
	 *  line running from it to the label. */
	let extentX = $derived(axisGutter + STRIP_WIDTH + 5);

	let axisRange = $derived(
		`${formatNumber(domain.min / axisUnit)}–${formatNumber(domain.max / axisUnit)}`
	);

	function width(slug: string): string | null {
		const feature = rows.get(slug)!.feature;
		if (feature.width_km === undefined) return null;
		return `${formatNumber(feature.width_km)} km`;
	}

	/** What a row owes its own width mark, the flex gaps beside it included.
	 *  The name is capped to what is left, so it truncates rather than pushing
	 *  "4,780,000 km" off the edge of the drawer. */
	function markRoom(width: string | null, summary: string): number {
		return (width?.length ?? 0) * MARK_CHAR + (summary ? 2 : 1) * ROW_GAP;
	}

	/** The row the pointer is on, keyed by its first slug. One state for the
	 *  label, the bracket and the strip section, so any of them lights all
	 *  three and opens the same tooltip. */
	let hovered = $state<string | null>(null);

	/** A row's band on the chart, never thinner than the eye can find. */
	function extent(group: string[]): { middle: number; half: number } {
		const from = y(Math.min(...group.map((slug) => rows.get(slug)!.inner)));
		const to = y(Math.max(...group.map((slug) => rows.get(slug)!.outer)));
		return { middle: (from + to) / 2, half: Math.max(1.5, (to - from) / 2) };
	}

	/** What a row opens into: a cluster lists its members, a feature drills into
	 *  its own. Undefined for a feature with nothing inside it, which has only
	 *  itself to explain and so stays a tooltip rather than a control. */
	function opensInto(group: string[]): Level | undefined {
		if (group.length > 1) return { cluster: group };
		return childSummary(rows, group[0]) ? { slug: group[0] } : undefined;
	}

	/** Pointer targets over the strip: a row's own band, widened to something
	 *  hoverable, drawn narrowest last so the specific feature wins. */
	let hitAreas = $derived.by(() =>
		placed
			.map((item) => ({ key: item.group[0], opens: opensInto(item.group), ...extent(item.group) }))
			.map((area) => ({ ...area, half: Math.max(area.half, 4) }))
			.sort((a, b) => b.half - a.half)
	);

	/** Prose for the level on screen: the ring system, or the feature drilled
	 *  into. Individual rings speak through their tooltip, and a group of them
	 *  has no prose of its own. */
	let detail = $derived.by(() => {
		const slug = drilledRow?.slug;
		if (!slug) return path.length ? {} : { text: system?.extract, url: system?.url };
		// Wikipedia where this locale has an article, else the PDS note, which
		// is English wherever it appears — better than an empty panel. The URL
		// only rides along with the extract: crediting Wikipedia for a PDS
		// sentence would be a false attribution, and a locale can have an
		// article link with no lead text.
		const article = localized?.[slug];
		if (article?.extract) return { text: article.extract, url: article.url };
		return { text: rows.get(slug)?.feature.note, url: undefined };
	});
</script>

{#snippet row(name: string, summary: string, width: string | null)}
	<!-- The width mark keeps its place at the right edge and never shrinks, so a
	     long name truncates instead of pushing "4,780,000 km" out of the drawer.
	     The name may not shrink either, since a fraction of a pixel of it is
	     enough to ellipsise a name that fits; what it gets is a cap. What gives
	     first is the child-count chip: "C ring" reading as "C …" loses more than
	     "4 gaps · …" does. -->
	<!-- `dir="auto"` because the chart forces LTR: without it a Hebrew or Arabic
	     ring name would ellipsise from its own beginning. -->
	<span
		dir="auto"
		class="shrink-0 truncate text-xs"
		style="max-width: calc(100% - {markRoom(width, summary)}px)">{name}</span
	>
	{#if summary}
		<span class="min-w-0 truncate font-mono text-[10px] text-sky-400">{summary} ›</span>
	{/if}
	<span class="ml-auto shrink-0 pl-1 font-mono text-[10px] text-muted-foreground"
		>{width ?? ''}</span
	>
{/snippet}

{#snippet stats(feature: RingFeature)}
	<!-- Associated moons are not here: they are the dots down the left of the
	     chart, where each one sits at the ring it shepherds. -->
	<div class="flex flex-wrap gap-x-3 gap-y-1 font-mono text-[11px] text-muted-foreground">
		{#if feature.optical_depth}
			<span>τ {formatOpticalDepth(feature.optical_depth)}</span>
		{/if}
		{#if feature.thickness_km}
			<span>{formatNumber(feature.thickness_km)} km {m.rings_thickness()}</span>
		{/if}
		{#if feature.eccentricity}
			<span>e {feature.eccentricity}</span>
		{/if}
		{#if feature.designation}
			<span>{feature.designation}</span>
		{/if}
	</div>
{/snippet}

{#snippet tooltip(slug: string)}
	{@const feature = rows.get(slug)!.feature}
	{@const summary = childSummary(rows, slug)}
	<div class="flex flex-col gap-1">
		<span dir="auto" class="font-medium">{label(slug)}</span>
		<!-- The row's chip is the first thing to get truncated when a name is
		     long ("2 ringlet…"), so the tooltip carries the whole count. -->
		{#if summary}
			<span class="font-mono text-[10px] text-sky-400">{summary}</span>
		{/if}
		{#if feature.note}
			<span class="text-xs">{feature.note}</span>
		{/if}
		{@render stats(feature)}
	</div>
{/snippet}

<div class="flex flex-col gap-3">
	<!-- Only once a ring is opened: at the top level the tab itself is the
	     heading, and the axis ticks already carry the range. Wraps rather than
	     overflowing — a deep breadcrumb plus a six-figure range is wider than
	     the drawer. -->
	{#if path.length}
		<div class="flex flex-wrap items-baseline justify-between gap-x-2 gap-y-0.5 text-sm">
			<!-- Crumbs are links to the level they name, the same deep link the row
			     itself carries. A cluster has no URL of its own, so that one crumb
			     is a plain control. -->
			<div class="flex flex-wrap items-center gap-1 font-medium">
				{#if systemHref}
					<a class={CRUMB_CLASS} href={systemHref} onclick={(e) => openLevel(e, [])}
						>{m.tab_rings()}</a
					>
				{:else}
					<button class={CRUMB_CLASS} onclick={() => (path = [])}>{m.tab_rings()}</button>
				{/if}
				{#each path as entry, i (i)}
					{@const href = i < path.length - 1 ? ringHref(entry) : undefined}
					<!-- No `rtl:rotate-180`: the drawer body is inside a ScrollArea, which
					     bits-ui renders `dir="ltr"` whatever the locale, so this row reads
					     left to right in Hebrew too and a flipped chevron would point away
					     from the crumb it separates. -->
					<ChevronRightIcon class="size-3 shrink-0 text-muted-foreground" />
					{#if href}
						<a class={CRUMB_CLASS} {href} onclick={(e) => openLevel(e, path.slice(0, i + 1))}
							>{levelLabel(entry)}</a
						>
					{:else if i < path.length - 1}
						<button class={CRUMB_CLASS} onclick={() => (path = path.slice(0, i + 1))}
							>{levelLabel(entry)}</button
						>
					{:else}
						<span>{levelLabel(entry)}</span>
					{/if}
				{/each}
			</div>
			<span class="shrink-0 font-mono text-[11px] text-muted-foreground">
				{axisRange}
				{axisInRadii ? m.rings_axis_body_radii() : m.rings_axis_km()}
			</span>
		</div>
	{/if}

	{#if detail.text}
		<ObjectDescription extract={detail.text} wikipediaUrl={detail.url} truncateLength={260} />
	{/if}

	{#if drilledRow}
		{@render stats(drilledRow.feature)}
	{/if}

	<!-- The plot is one left-to-right composition — moon dots, axis gutter,
	     strip, then leader lines out to the labels — and the SVG's coordinates
	     cannot follow the document direction. Stated rather than inherited: the
	     drawer's ScrollArea happens to force LTR today, and if that is ever
	     fixed the flex here must not reverse out from under the SVG. -->
	<div dir="ltr" class="relative flex gap-2 overflow-hidden rounded-md border bg-card/40 p-3">
		<!-- Every moon the axis reaches, at its own mean orbit, widening to the
		     left where several share one. No labels: forty names down the edge
		     would crowd out the chart, and the tooltip is a hover away. -->
		<!-- Butted against the axis gutter (the row gap cancelled): the ticks are
		     right-aligned, so the space the dots take there was empty. -->
		<div
			class="relative -mr-2 shrink-0"
			style="width: {moonDots.width}px; height: {chartHeight + 8}px"
		>
			{#each moonDots.dots as dot (dot.name)}
				{@const href = moonHref(dot)}
				{@const dotClass = 'absolute rounded-full ring-1 ring-black/50'}
				{@const dotStyle = `top: ${dot.top + 4 - dot.size / 2}px; left: ${dot.left}px; width: ${dot.size}px; height: ${dot.size}px; background-color: ${dot.color}`}
				<Tooltip.Root>
					<Tooltip.Trigger>
						{#snippet child({ props })}
							{#if href}
								<a
									{...props}
									{href}
									onclick={(e) => focusMoon(e, dot)}
									class="{dotClass} hover:ring-foreground"
									style={dotStyle}
									aria-label={dot.name}
								></a>
							{:else}
								<span {...props} class="{dotClass} cursor-help" style={dotStyle}></span>
							{/if}
						{/snippet}
					</Tooltip.Trigger>
					<Tooltip.Content>{dot.name}</Tooltip.Content>
				</Tooltip.Root>
			{/each}
		</div>

		<!-- Axis + optical-depth strip. The band opacity is the ring's normal
		     optical depth on a log ramp, so a gap reads as empty. -->
		<svg
			width={axisGutter + STRIP_WIDTH + LEADER_WIDTH}
			height={chartHeight + 8}
			class="shrink-0"
			aria-hidden="true"
		>
			<g transform="translate(0 4)">
				{#each axisTicks as tick (tick.y)}
					<text
						x={axisGutter - 6}
						y={tick.y + 3}
						text-anchor="end"
						class="fill-muted-foreground font-mono text-[9px]">{tick.text}</text
					>
					<line x1={axisGutter - 4} x2={axisGutter} y1={tick.y} y2={tick.y} class="stroke-border" />
				{/each}
				<rect x={axisGutter} y="0" width={STRIP_WIDTH} height={chartHeight} class="fill-black/50" />
				{#if stripImage}
					<image
						href={stripImage}
						x={axisGutter}
						y="0"
						width={STRIP_WIDTH}
						height={chartHeight}
						preserveAspectRatio="none"
					/>
				{:else}
					<!-- Server-rendered, or no canvas: bands straight from the catalogue. -->
					{#each visible as slug (slug)}
						{@const row = rows.get(slug)!}
						{@const top = y(row.inner)}
						<rect
							x={axisGutter}
							y={top}
							width={STRIP_WIDTH}
							height={Math.max(1.2, y(row.outer) - top)}
							fill="currentColor"
							opacity={opacity(row.feature)}
							class="text-slate-100"
						/>
					{/each}
				{/if}
				<!-- Excised void: the axis jumps here, and says so. Two parallel
				     rules across the strip, the radii either side already labelled
				     by the run's own ticks. -->
				{#each axis.runs.slice(1) as run (run.from)}
					{@const cut = run.top - BREAK_HEIGHT / 2}
					<rect
						x={axisGutter - 6}
						y={cut - 3}
						width={STRIP_WIDTH + 12}
						height="6"
						class="fill-card"
					/>
					{#each [-3, 3] as offset (offset)}
						<line
							x1={axisGutter - 6}
							x2={axisGutter + STRIP_WIDTH + 6}
							y1={cut + offset}
							y2={cut + offset}
							class="stroke-muted-foreground/70"
						/>
					{/each}
				{/each}
				<!-- Each row's own extent, bracketed beside the strip: the profile
				     shows where the material is, not where one named feature ends
				     and the next begins, and a boundary the eye cannot find is a
				     row pointing at nothing. Hovering a row — its label or its
				     stretch of strip — lifts the whole set out. -->
				{#each placed as item (item.group[0])}
					{@const key = item.group[0]}
					{@const on = hovered === key}
					{@const box = extent(item.group)}
					{#if on}
						<rect
							x={axisGutter}
							y={box.middle - box.half}
							width={STRIP_WIDTH}
							height={box.half * 2}
							class="fill-white/10 stroke-foreground/80"
						/>
					{/if}
					<path
						d="M{extentX - 4} {box.middle - box.half} L{extentX} {box.middle -
							box.half} L{extentX} {box.middle + box.half} L{extentX - 4} {box.middle + box.half}"
						fill="none"
						stroke-width={on ? 2.5 : 1.5}
						class={on ? 'stroke-foreground' : 'stroke-muted-foreground'}
					/>
					<polyline
						points="{extentX},{item.bandY} {extentX + 4},{item.bandY} {extentX +
							8},{item.top} {axisGutter + STRIP_WIDTH + LEADER_WIDTH},{item.top}"
						fill="none"
						class={on ? 'stroke-foreground/80' : 'stroke-muted-foreground/40'}
					/>
				{/each}
				<!-- Hit areas over the strip. Narrowest last, so where a ringlet
				     sits inside a ring the pointer lands on the ringlet. A stretch
				     of strip is the same control as the label beside it: it opens
				     what it holds. Hidden from assistive tech, since the label is
				     the same target with a name and a tab stop. -->
				{#each hitAreas as area (area.key)}
					{@const opens = area.opens}
					{@const href = opens ? ringHref(opens) : undefined}
					{@const band = {
						x: axisGutter,
						y: area.middle - area.half,
						width: STRIP_WIDTH,
						height: area.half * 2,
						fill: 'transparent',
						onmouseenter: () => (hovered = area.key),
						onmouseleave: () => (hovered = null)
					}}
					{#if opens && href}
						<a
							{href}
							tabindex="-1"
							aria-hidden="true"
							onclick={(e) => openLevel(e, [...path, opens])}
						>
							<rect {...band} class="cursor-pointer" />
						</a>
					{:else if opens}
						<!-- A cluster has no link to give, so the strip is a bare control. -->
						<rect
							{...band}
							class="cursor-pointer"
							aria-hidden="true"
							onclick={() => (path = [...path, opens])}
						/>
					{:else}
						<rect {...band} class="cursor-help" aria-hidden="true" />
					{/if}
				{/each}
			</g>
		</svg>

		<div class="relative grow" style="height: {chartHeight + 8}px">
			{#each placed as item (item.group[0])}
				{@const grouped = item.group.length > 1}
				{@const slug = item.group[0]}
				{@const name = grouped
					? `${label(slug)}–${label(item.group[item.group.length - 1])}`
					: label(slug)}
				{@const summary = grouped ? kindSummary(rows, item.group) : childSummary(rows, slug)}
				{@const opens = opensInto(item.group)}
				{@const href = opens ? ringHref(opens) : undefined}
				{@const rowClass =
					'absolute inset-x-0 flex w-full items-center gap-2 text-left ' +
					(opens ? 'hover:text-sky-300' : 'cursor-help')}
				<Tooltip.Root
					open={hovered === slug}
					onOpenChange={(open) => {
						if (open) hovered = slug;
						else if (hovered === slug) hovered = null;
					}}
				>
					<Tooltip.Trigger>
						{#snippet child({ props })}
							{#if opens && href}
								<!-- Anything with something inside it navigates; a lone feature
								     only explains itself, so it is a tooltip target, not a control. -->
								<a
									{...props}
									{href}
									class={rowClass}
									style="top: {item.top - 4}px"
									onmouseenter={() => (hovered = slug)}
									onmouseleave={() => (hovered = null)}
									onclick={(e) => openLevel(e, [...path, opens])}
								>
									{@render row(name, summary, grouped ? null : width(slug))}
								</a>
							{:else if opens}
								<!-- A cluster is a row this scale invented; nothing to link to. -->
								<button
									{...props}
									class={rowClass}
									style="top: {item.top - 4}px"
									onmouseenter={() => (hovered = slug)}
									onmouseleave={() => (hovered = null)}
									onclick={() => (path = [...path, opens])}
								>
									{@render row(name, summary, grouped ? null : width(slug))}
								</button>
							{:else}
								<div
									{...props}
									class={rowClass}
									style="top: {item.top - 4}px"
									role="presentation"
									onmouseenter={() => (hovered = slug)}
									onmouseleave={() => (hovered = null)}
								>
									{@render row(name, summary, width(slug))}
								</div>
							{/if}
						{/snippet}
					</Tooltip.Trigger>
					<Tooltip.Content class="max-w-[16rem]">
						{#if grouped}
							<span class="text-xs">{item.group.map(label).join(', ')}</span>
						{:else}
							{@render tooltip(slug)}
						{/if}
					</Tooltip.Content>
				</Tooltip.Root>
			{/each}
		</div>
	</div>

	<div class="flex items-center gap-2 px-1 text-[10px] text-muted-foreground">
		<span>{m.rings_invisible()}</span>
		<!-- Fixed left-to-right, like the labels either side of it: Tailwind's
		     `rtl:` variant keys on an ancestor `dir`, so an RTL override here
		     would flip the ramp under a row the ScrollArea keeps LTR. -->
		<span class="h-1.5 grow rounded-full bg-linear-to-r from-slate-400/6 to-slate-200"></span>
		<span>{m.rings_opaque()}</span>
		<span>· {m.rings_optical_depth()}</span>
	</div>
</div>
