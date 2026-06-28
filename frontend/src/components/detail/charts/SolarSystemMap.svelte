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
		const ordered = [...file.objects].sort((a, b) => a.a - b.a);
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
				fill: o.color || BODY_COLORS[o.id] || DEFAULT_BODY_COLOR
			});
		}
		return placed;
	});

	let sun = $derived(file?.objects.find((o) => o.kind === 'star') ?? null);
	const SUN_R = (SUN_KM / 2) * PX_PER_KM;
	const SUN_CX = X_LEFT - 2 - SUN_R; // right limb sits just left of the first planet

	let planets = $derived(bodies.filter((b) => b.kind !== 'star'));

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
	let hoveredBeltSlug = $state<string | null>(null);
	let containerW = $state(0);

	interface Tip {
		cx: number; // viewBox x the tooltip centers on
		cy: number; // viewBox y the tooltip sits above
		title: string;
		sub: string;
	}
	// One tooltip serves the Sun, the bodies and the belt bands.
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
				<!-- Transparent hit target so tiny dots stay clickable/hoverable. -->
				<circle cx={b.cx} cy={b.cy} r={Math.max(b.r, 11)} fill="transparent" />
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
