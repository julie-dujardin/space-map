<script lang="ts" module>
	// Log heliocentric distance (x) × true relative diameter (size), with each
	// body nudged vertically by its orbital inclination. A "minimap" of the solar
	// system that doubles as a zone picker — click a body to fly there, click a
	// belt to open its group. Far scattered bodies (Eris, Sedna) clip off the
	// right edge into the real map; the Sun is real-scale and clips off the left.

	const VIEW_W = 720;
	const VIEW_H = 240;
	const X_LEFT = 44;
	const X_RIGHT = 700;
	const CY = 116; // ecliptic baseline, raised to leave room for belt labels

	const A_MIN = 0.3; // log-axis domain [AU]; Sun (a=0) is framed separately
	const A_MAX = 50;
	const LOG_MIN = Math.log10(A_MIN);
	const LOG_SPAN = Math.log10(A_MAX) - LOG_MIN;

	// Radius px per km, tuned so Jupiter reads at ~16 px. Linear & shared with the
	// Sun, so the Sun genuinely dwarfs everything (≈156 px → mostly offscreen).
	const PX_PER_KM = 2.24e-4;
	const MIN_R = 2.4; // floor so the inner planets / dwarfs stay visible dots
	const SUN_KM = 1_391_400; // diameter

	const PX_PER_DEG = 1.8; // inclination → vertical offset
	const MAX_OFFSET = 82;

	const MOON_GAP = 4; // px between a planet's top edge and its first moon
	const MOON_SPACING = 3; // px between stacked moons

	// Hit targets are padded well beyond the dots: the chart renders at ~0.4×, so
	// a viewBox unit is a fraction of a device pixel.
	const HIT_MARGIN = 16;
	const MOON_ZONE_W = 34; // width of the per-planet moon hover/click zone
	const MOON_ZONE_PAD = 7; // vertical padding around the moon stack

	const RING_TILT = -18; // deg, the ring ellipse's apparent tilt
	const RING_FORESHORTEN = 0.42; // ry/rx — how edge-on the rings read

	const AXIS_TICKS = [0.3, 1, 3, 10, 30];

	const TIP_HALF = 64; // px; keeps the tooltip's center this far from either edge
	const TIP_H = 28; // px; approx tooltip height, to seat it above the anchor

	function xOf(a: number): number {
		return X_LEFT + ((Math.log10(a) - LOG_MIN) / LOG_SPAN) * (X_RIGHT - X_LEFT);
	}
</script>

<script lang="ts">
	import { getContext, untrack } from 'svelte';
	import { BODY_COLORS, DEFAULT_BODY_COLOR } from '$lib/constants';
	import type { AppState } from '$lib/state/app-state.svelte';
	import type { FocusObject } from '$lib/state/focusable';
	import { focusHref, focusClick, isModifiedClick } from '$lib/state/focus-link';
	import { applyGroup, serializeUrl } from '$lib/state/url';
	import {
		fetchSolarSystemMap,
		type SolarSystemMapFile,
		type SolarSystemMapObject,
		type SolarSystemMapBelt
	} from '$lib/fetch/groups/solar-system-map';

	interface Props {
		ariaLabel: string;
		/** Object.id → localized label, overriding the exported English name. */
		localizedNames?: Record<string, string>;
	}
	let { ariaLabel, localizedNames }: Props = $props();

	const appState = getContext<AppState | undefined>('appState');
	const focusObject = getContext<FocusObject | undefined>('focusObject');

	let file = $state<SolarSystemMapFile | null>(null);
	$effect(() => {
		untrack(() =>
			fetchSolarSystemMap()
				.then((f) => (file = f))
				.catch((e) => console.error('Solar system map failed to load', e))
		);
	});

	/** Strip a leading minor-planet designation ("50000 Quaoar" → "Quaoar") and
	 *  tidy ALL-CAPS catalogue names; the localized label wins when present. */
	function displayName(o: SolarSystemMapObject): string {
		const local = localizedNames?.[o.id];
		if (local) return local;
		const stripped = o.name.replace(/^\d+\s+/, '');
		if (stripped === stripped.toUpperCase() && /[A-Z]/.test(stripped))
			return stripped.charAt(0) + stripped.slice(1).toLowerCase();
		return stripped;
	}

	interface PlacedBody {
		id: string;
		name: string;
		kind: SolarSystemMapObject['kind'];
		a: number;
		i: number;
		cx: number;
		cy: number;
		r: number;
		fill: string;
		rings?: { inner: number; outer: number };
		moonCount?: number;
	}

	function minDistance(cx: number, cy: number, placed: PlacedBody[]): number {
		let min = Infinity;
		for (const p of placed) min = Math.min(min, Math.hypot(p.cx - cx, p.cy - cy));
		return min;
	}

	let bodies = $derived.by<PlacedBody[]>(() => {
		if (!file) return [];
		// Inclination magnitude sets the vertical offset; the sign (above vs below
		// the ecliptic) is chosen greedily to sit farthest from already-placed
		// bodies, so same-distance / same-inclination pairs (Haumea & Makemake)
		// split to opposite sides instead of overlapping.
		// Moons don't belong on the heliocentric axis — they stack on their planet
		// (see placedMoons); everything else is placed by distance here.
		const ordered = file.objects.filter((o) => o.kind !== 'moon').sort((a, b) => a.a - b.a);
		const placed: PlacedBody[] = [];
		for (const o of ordered) {
			const r = o.kind === 'star' ? 0 : Math.max(MIN_R, (o.diameter_km / 2) * PX_PER_KM);
			const cx = o.kind === 'star' ? 0 : xOf(o.a);
			let cy = CY;
			if (o.kind !== 'star' && o.i > 0) {
				const offset = Math.min(o.i * PX_PER_DEG, MAX_OFFSET);
				const up = CY - offset;
				const down = CY + offset;
				cy = minDistance(cx, up, placed) >= minDistance(cx, down, placed) ? up : down;
			}
			placed.push({
				id: o.id,
				name: displayName(o),
				kind: o.kind,
				a: o.a,
				i: o.i,
				cx,
				cy,
				r,
				fill: o.color || BODY_COLORS[o.id] || DEFAULT_BODY_COLOR,
				rings: o.rings,
				moonCount: o.moon_count
			});
		}
		return placed;
	});

	let sun = $derived(file?.objects.find((o) => o.kind === 'star') ?? null);
	const SUN_R = (SUN_KM / 2) * PX_PER_KM;
	const SUN_CX = X_LEFT - 2 - SUN_R; // right limb sits just left of the first planet

	let planets = $derived(bodies.filter((b) => b.kind !== 'star'));

	interface PlacedMoon {
		id: string;
		name: string;
		parentId: string;
		parentName: string;
		parentMoonCount: number;
		linkParent: boolean;
		cx: number;
		cy: number;
		r: number;
		fill: string;
	}
	// Major moons stack straight up from their planet, largest nearest it, above
	// the planet's rings if any.
	let placedMoons = $derived.by<PlacedMoon[]>(() => {
		if (!file) return [];
		const byId = new Map(bodies.map((b) => [b.id, b]));
		const groups = new Map<string, SolarSystemMapObject[]>();
		for (const o of file.objects) {
			if (o.kind !== 'moon' || !o.parent) continue;
			const g = groups.get(o.parent);
			if (g) g.push(o);
			else groups.set(o.parent, [o]);
		}
		const out: PlacedMoon[] = [];
		for (const [parentId, moons] of groups) {
			const parent = byId.get(parentId);
			if (!parent) continue;
			const ringTop = parent.rings ? parent.r * parent.rings.outer * RING_FORESHORTEN : 0;
			let y = parent.cy - Math.max(parent.r, ringTop) - MOON_GAP;
			for (const m of [...moons].sort((a, b) => b.diameter_km - a.diameter_km)) {
				const r = Math.max(MIN_R, (m.diameter_km / 2) * PX_PER_KM);
				y -= r;
				out.push({
					id: m.id,
					name: displayName(m),
					parentId,
					parentName: parent.name,
					parentMoonCount: parent.moonCount ?? 0,
					linkParent: m.link_parent ?? false,
					cx: parent.cx,
					cy: y,
					r,
					fill: m.color || BODY_COLORS[m.id] || DEFAULT_BODY_COLOR
				});
				y -= r + MOON_SPACING;
			}
		}
		return out;
	});

	interface MoonZone {
		parentId: string;
		parentName: string;
		parentMoonCount: number;
		linkParent: boolean;
		moonId: string; // representative (largest) moon — the single-moon link/name
		moonName: string;
		x: number;
		y: number;
		width: number;
		height: number;
	}
	// One hover/click zone covers each planet's whole moon stack — the tooltip
	// reads the planet, not the individual moon, so per-moon targets aren't needed.
	let moonZones = $derived.by<MoonZone[]>(() => {
		const groups = new Map<string, PlacedMoon[]>();
		for (const mn of placedMoons) {
			const g = groups.get(mn.parentId);
			if (g) g.push(mn);
			else groups.set(mn.parentId, [mn]);
		}
		const out: MoonZone[] = [];
		for (const [parentId, moons] of groups) {
			const top = Math.min(...moons.map((mn) => mn.cy - mn.r));
			const bottom = Math.max(...moons.map((mn) => mn.cy + mn.r));
			const first = moons[0]; // largest, nearest the planet
			out.push({
				parentId,
				parentName: first.parentName,
				parentMoonCount: first.parentMoonCount,
				linkParent: first.linkParent,
				moonId: first.id,
				moonName: first.name,
				x: first.cx - MOON_ZONE_W / 2,
				y: top - MOON_ZONE_PAD,
				width: MOON_ZONE_W,
				height: bottom - top + 2 * MOON_ZONE_PAD
			});
		}
		return out;
	});

	interface PlacedBelt extends SolarSystemMapBelt {
		x: number;
		width: number;
		href: string | undefined;
	}
	let belts = $derived.by<PlacedBelt[]>(() => {
		if (!file || !appState) return [];
		return file.belts.map((b) => {
			const x = xOf(b.inner_au);
			return {
				...b,
				x,
				width: xOf(b.outer_au) - x,
				href: serializeUrl(applyGroup(appState.view, b.slug, b.label))
			};
		});
	});

	let hoveredId = $state<string | null>(null);
	let hoveredMoonZone = $state<string | null>(null);
	let hoveredBeltSlug = $state<string | null>(null);
	let containerW = $state(0);

	interface Tip {
		cx: number; // viewBox x the tooltip centers on
		cy: number; // viewBox y the tooltip sits above
		title: string;
		sub: string;
	}
	// One tooltip serves the Sun, the bodies, the moons and the belt bands.
	let tip = $derived.by<Tip | null>(() => {
		if (sun && hoveredId === sun.id)
			return { cx: X_LEFT, cy: 40, title: displayName(sun), sub: '' };
		const b = planets.find((p) => p.id === hoveredId);
		if (b)
			return {
				cx: b.cx,
				cy: b.cy - b.r - 4,
				title: b.name,
				sub: `${b.a.toFixed(b.a < 10 ? 1 : 0)} AU`
			};
		const zone = moonZones.find((z) => z.parentId === hoveredMoonZone);
		if (zone) {
			const cx = zone.x + zone.width / 2;
			// Giants read as "Planet · N moons"; Earth's single Moon keeps its name.
			return zone.linkParent
				? { cx, cy: zone.y, title: zone.parentName, sub: `${zone.parentMoonCount} moons` }
				: { cx, cy: zone.y, title: zone.moonName, sub: zone.parentName };
		}
		const belt = belts.find((bl) => bl.slug === hoveredBeltSlug);
		if (belt)
			return {
				cx: belt.x + belt.width / 2,
				cy: 44,
				title: belt.label,
				sub: `${belt.inner_au.toFixed(1)}–${belt.outer_au.toFixed(0)} AU`
			};
		return null;
	});

	function openGroup(slug: string, label: string) {
		return (e: MouseEvent) => {
			if (isModifiedClick(e) || !appState) return;
			e.preventDefault();
			appState.setGroup(slug, label);
		};
	}
</script>

<div class="bg-muted/30 relative w-full overflow-hidden rounded-md" bind:clientWidth={containerW}>
	<svg
		viewBox="0 0 {VIEW_W} {VIEW_H}"
		class="text-muted-foreground block h-auto w-full"
		role="group"
		aria-label={ariaLabel}
	>
		<defs>
			<radialGradient id="ssmap-sun" cx="50%" cy="50%" r="50%">
				<stop offset="0%" stop-color="#fff4c2" />
				<stop offset="55%" stop-color="#ffdd44" />
				<stop offset="100%" stop-color="#f0a23c" />
			</radialGradient>
			<pattern id="ssmap-belt" width="9" height="9" patternUnits="userSpaceOnUse">
				<circle cx="2" cy="2" r="0.9" fill="currentColor" opacity="0.55" />
				<circle cx="6.5" cy="6" r="0.9" fill="currentColor" opacity="0.55" />
			</pattern>
		</defs>

		<!-- Axis: faint gridlines + AU·log ticks along the top. -->
		{#each AXIS_TICKS as t (t)}
			<line
				x1={xOf(t)}
				x2={xOf(t)}
				y1="20"
				y2={VIEW_H - 28}
				stroke="currentColor"
				stroke-width="0.5"
				opacity="0.12"
			/>
			<text
				x={xOf(t)}
				y="16"
				text-anchor="middle"
				font-size="16"
				fill="currentColor"
				opacity="0.85"
			>
				{t}
			</text>
		{/each}
		<text x={X_RIGHT} y="16" text-anchor="end" font-size="14" fill="currentColor" opacity="0.65">
			AU · log
		</text>

		<!-- Belt bands (behind the bodies); the whole band links to its group. -->
		{#each belts as belt (belt.slug)}
			<a
				href={belt.href}
				onclick={openGroup(belt.slug, belt.label)}
				onpointerenter={() => (hoveredBeltSlug = belt.slug)}
				onpointerleave={() => hoveredBeltSlug === belt.slug && (hoveredBeltSlug = null)}
				onfocus={() => (hoveredBeltSlug = belt.slug)}
				onblur={() => hoveredBeltSlug === belt.slug && (hoveredBeltSlug = null)}
				aria-label={belt.label}
			>
				<rect
					x={belt.x}
					y="26"
					width={belt.width}
					height={VIEW_H - 60}
					fill="url(#ssmap-belt)"
					class={belt.kind === 'kuiper_belt' ? 'text-sky-400/70' : 'text-muted-foreground'}
				/>
				<text
					x={belt.x + belt.width / 2}
					y={VIEW_H - 8}
					text-anchor="middle"
					font-size="18"
					class="font-semibold {belt.kind === 'kuiper_belt'
						? 'fill-sky-400'
						: 'fill-muted-foreground'}"
				>
					{belt.label}
				</text>
			</a>
		{/each}

		<!-- The Sun: real-scale, framed so only its right limb shows. A focus link
		     like the bodies (middle/⌘-click opens the real URL). -->
		{#if sun}
			{@const s = sun}
			<a
				href={focusHref(appState, s.id, displayName(s))}
				onclick={focusClick(focusObject, s.id, displayName(s))}
				onpointerenter={() => (hoveredId = s.id)}
				onpointerleave={() => hoveredId === s.id && (hoveredId = null)}
				onfocus={() => (hoveredId = s.id)}
				onblur={() => hoveredId === s.id && (hoveredId = null)}
				aria-label={displayName(s)}
			>
				<circle cx={SUN_CX} cy={CY} r={SUN_R} fill="url(#ssmap-sun)" />
			</a>
		{/if}

		<!-- Ringed planets (Saturn): a tilted, foreshortened band behind the dot.
		     stroke-width is the ring thickness; radius is its mid-line. -->
		{#each planets as b (b.id)}
			{#if b.rings}
				{@const mid = (b.r * (b.rings.inner + b.rings.outer)) / 2}
				<ellipse
					cx={b.cx}
					cy={b.cy}
					rx={mid}
					ry={mid * RING_FORESHORTEN}
					transform="rotate({RING_TILT} {b.cx} {b.cy})"
					fill="none"
					stroke="#d9c89f"
					stroke-width={b.r * (b.rings.outer - b.rings.inner)}
					opacity="0.45"
				/>
			{/if}
		{/each}

		<!-- Bodies: each is a focus link (middle/⌘-click opens the real URL). -->
		{#each planets as b (b.id)}
			<a
				href={focusHref(appState, b.id, b.name)}
				onclick={focusClick(focusObject, b.id, b.name)}
				onpointerenter={() => (hoveredId = b.id)}
				onpointerleave={() => hoveredId === b.id && (hoveredId = null)}
				onfocus={() => (hoveredId = b.id)}
				onblur={() => hoveredId === b.id && (hoveredId = null)}
				aria-label={b.name}
			>
				{#if hoveredId === b.id}
					<circle
						cx={b.cx}
						cy={b.cy}
						r={b.r + 3.5}
						fill="none"
						stroke="currentColor"
						stroke-width="1"
						opacity="0.8"
					/>
				{/if}
				<circle cx={b.cx} cy={b.cy} r={b.r} fill={b.fill} />
				<!-- Transparent hit target — a generous margin around the dot, since the
				     chart renders at ~0.4× so viewBox units are well under a device px. -->
				<circle cx={b.cx} cy={b.cy} r={b.r + HIT_MARGIN} fill="transparent" />
			</a>
		{/each}

		<!-- Moon stacks: dots, a per-planet hover highlight, and one hit zone per
		     planet covering the whole stack (the tooltip reads the planet, not the
		     individual moon). The zone links to the moons tab, or to the moon itself
		     when the planet has too few moons for a tab (Earth). -->
		{#each moonZones as z (z.parentId)}
			{#if hoveredMoonZone === z.parentId}
				<rect
					x={z.x}
					y={z.y}
					width={z.width}
					height={z.height}
					rx="4"
					fill="currentColor"
					opacity="0.1"
				/>
			{/if}
		{/each}
		{#each placedMoons as mn (mn.id)}
			<circle cx={mn.cx} cy={mn.cy} r={mn.r} fill={mn.fill} />
		{/each}
		{#each moonZones as z (z.parentId)}
			<a
				href={z.linkParent
					? focusHref(appState, z.parentId, z.parentName, 'members')
					: focusHref(appState, z.moonId, z.moonName)}
				onclick={z.linkParent
					? focusClick(focusObject, z.parentId, z.parentName, { tab: 'members' })
					: focusClick(focusObject, z.moonId, z.moonName)}
				onpointerenter={() => (hoveredMoonZone = z.parentId)}
				onpointerleave={() => hoveredMoonZone === z.parentId && (hoveredMoonZone = null)}
				onfocus={() => (hoveredMoonZone = z.parentId)}
				onblur={() => hoveredMoonZone === z.parentId && (hoveredMoonZone = null)}
				aria-label={z.linkParent ? `${z.parentName} moons` : z.moonName}
			>
				<rect x={z.x} y={z.y} width={z.width} height={z.height} fill="transparent" />
			</a>
		{/each}
	</svg>

	<!-- Tooltip overlay, positioned in px and clamped to the chart box so it can't
	     spill past any edge (the chart itself is overflow-clipped). The aspect is
	     fixed, so a viewBox unit maps to containerW/VIEW_W px on both axes. -->
	{#if tip}
		{@const cxPx = (tip.cx / VIEW_W) * containerW}
		{@const leftPx = Math.min(Math.max(cxPx, TIP_HALF), Math.max(TIP_HALF, containerW - TIP_HALF))}
		{@const topPx = Math.max(4, (tip.cy / VIEW_W) * containerW - TIP_H)}
		<div
			class="bg-background/90 text-foreground pointer-events-none absolute z-10 -translate-x-1/2 rounded px-2 py-1 text-xs whitespace-nowrap shadow-sm backdrop-blur-sm"
			style="left: {leftPx}px; top: {topPx}px"
		>
			<span class="font-medium">{tip.title}</span>
			{#if tip.sub}<span class="text-muted-foreground">· {tip.sub}</span>{/if}
		</div>
	{/if}
</div>
