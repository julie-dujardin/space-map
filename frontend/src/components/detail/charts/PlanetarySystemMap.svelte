<script lang="ts" module>
	// A planetary system on the same terms as the Solar System minimap: the
	// primary framed off the left edge, its moons on a log orbital-distance axis
	// at true relative diameters, nudged vertically by inclination. Distances are
	// in primary radii, which is what makes one system readable against another.

	const VIEW_W = 720;
	const VIEW_H = 240;
	const X_LEFT = 44;
	const X_RIGHT = 700;
	const CY = 124; // orbital baseline, low enough to leave room for the ring label

	// Sizes are linear and scaled so the largest moon reads at TOP_MOON_R, which
	// keeps moon-against-moon true within a system — the comparison the page is
	// about. The primary is at the same scale, right limb pinned just left of the
	// axis: a giant runs off the left edge as a wall, a Pluto-sized primary sits
	// there as a whole disc. Same framing as the Solar System map's Sun.
	const TOP_MOON_R = 14;
	const MIN_R = 1.9; // floor so the small irregulars stay visible dots
	const PLANET_LIMB_X = X_LEFT - 4;
	const PLANET_RIM = 10; // px of limb shading, fixed so a wall-sized primary keeps a visible edge

	const PX_PER_DEG = 0.62; // inclination → vertical offset
	const MAX_OFFSET = 84;

	const HIT_MARGIN = 14;

	const DRAG_SLOP = 8;

	/** Axis ticks, in primary radii — the decade ladder, trimmed to the domain. */
	const TICK_LADDER = [1, 2, 3, 5, 10, 20, 30, 50, 100, 200, 300, 500, 1000, 2000, 5000];

	// Tile crop: the primary's limb and the moons nearest it, framed so the
	// baseline rides in the upper third — the card's caption takes the lower half,
	// and moons drawn behind the text read as dirt on the picture.
	const BG_VIEW = '0 96 320 144';

	/** A moon going the other way round its primary. Called out in the tooltip
	 *  only: every moon is drawn the same, so size and distance stay the chart's
	 *  two variables. */
	function isRetrograde(tiltDeg: number): boolean {
		return tiltDeg > 90;
	}
</script>

<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import { formatDistance } from '$lib/format/distance';
	import { AU_KM } from '$lib/math/units';
	import type { AppState } from '$lib/state/app-state.svelte';
	import type { FocusObject } from '$lib/state/focusable';
	import { getContext } from 'svelte';
	import ChartTip from './ChartTip.svelte';
	import { focusHref, focusClick } from '$lib/state/focus-link';
	import type { PlanetarySystem, SystemMoon } from './planetary-system.svelte';

	interface Props {
		system: PlanetarySystem;
		ariaLabel: string;
		/** 'background' strips the axis, labels, links and tooltips and fills+crops
		 *  its box — a static diagram behind a cross-ref tile. Anchored left, so the
		 *  crop keeps the primary's limb and the inner moons rather than the empty
		 *  middle of the axis. */
		variant?: 'hero' | 'background';
	}
	let { system, ariaLabel, variant = 'hero' }: Props = $props();
	let isBackground = $derived(variant === 'background');

	const appState = getContext<AppState | undefined>('appState');
	const focusObject = getContext<FocusObject | undefined>('focusObject');

	// Log domain over the moons actually present, widened to take in the rings and
	// padded a little either side so nothing sits on an edge.
	let domain = $derived.by(() => {
		let lo = Math.min(...system.moons.map((mn) => mn.aRp));
		let hi = Math.max(...system.moons.map((mn) => mn.aRp));
		if (system.rings) {
			lo = Math.min(lo, system.rings.innerRp);
			hi = Math.max(hi, system.rings.outerRp);
		}
		if (hi <= lo) {
			// A lone moon has no span of its own; give it one centred on itself.
			lo /= 2;
			hi *= 2;
		}
		lo = Math.max(1, lo);
		const logLo = Math.log10(lo) - 0.12;
		const logHi = Math.log10(hi) + 0.12;
		return { logLo, logSpan: logHi - logLo };
	});

	function xOf(rp: number): number {
		const t = (Math.log10(Math.max(rp, 1e-6)) - domain.logLo) / domain.logSpan;
		return X_LEFT + t * (X_RIGHT - X_LEFT);
	}

	let ticks = $derived(
		TICK_LADDER.filter((t) => {
			const x = xOf(t);
			return x >= X_LEFT - 1 && x <= X_RIGHT + 1;
		})
	);

	/** Real units for the tooltips; the axis alone keeps primary radii, which is
	 *  what makes one system comparable with another. */
	function kmLabel(rp: number): string {
		return formatDistance((rp * system.planetRadiusKm) / AU_KM);
	}

	interface PlacedMoon extends SystemMoon {
		cx: number;
		cy: number;
		r: number;
	}

	function minDistance(cx: number, cy: number, placed: PlacedMoon[]): number {
		let min = Infinity;
		for (const p of placed) min = Math.min(min, Math.hypot(p.cx - cx, p.cy - cy));
		return min;
	}

	// Sized off the largest *measured* moon: most of a giant's swarm is
	// designation-only with no radius at all, and one of those in the max would
	// take the whole scale to NaN.
	let kmToPx = $derived(
		TOP_MOON_R / Math.max(...system.moons.map((mn) => mn.radiusKm).filter((r) => r > 0), 1)
	);
	let planetR = $derived(system.planetRadiusKm * kmToPx);
	let planetCx = $derived(PLANET_LIMB_X - planetR);

	// Same greedy placement as the Solar System map: inclination sets the vertical
	// offset and its sign goes wherever there is more room, so the crowded
	// irregular swarms spread across the baseline instead of stacking on it.
	let placed = $derived.by<PlacedMoon[]>(() => {
		const out: PlacedMoon[] = [];
		for (const mn of system.moons) {
			const cx = xOf(mn.aRp);
			const r = mn.radiusKm > 0 ? Math.max(MIN_R, mn.radiusKm * kmToPx) : MIN_R;
			let cy = CY;
			if (mn.tiltDeg > 0) {
				// Retrograde orbits fold back from 180°, so the offset reads "tilt away
				// from the equator" for both senses rather than running off the chart.
				const tilt = mn.tiltDeg > 90 ? 180 - mn.tiltDeg : mn.tiltDeg;
				const offset = Math.min(tilt * PX_PER_DEG, MAX_OFFSET);
				const up = CY - offset;
				const down = CY + offset;
				cy = minDistance(cx, up, out) >= minDistance(cx, down, out) ? up : down;
			}
			out.push({ ...mn, cx, cy, r });
		}
		return out;
	});

	let ringBand = $derived.by(() => {
		if (!system.rings) return null;
		const x = xOf(system.rings.innerRp);
		const width = xOf(system.rings.outerRp) - x;
		return width > 0.5 ? { x, width } : null;
	});

	let hoveredId = $state<string | null>(null);
	let hoveredRings = $state(false);
	let containerW = $state(0);

	interface Tip {
		cx: number;
		cy: number;
		title: string;
		sub: string;
	}
	let tip = $derived.by<Tip | null>(() => {
		if (hoveredId === system.planet.data.id)
			return {
				cx: Math.max(X_LEFT, planetCx),
				cy: CY - Math.min(planetR, CY - 40),
				title: system.planetName,
				sub: m.planetary_system_primary()
			};
		const mn = placed.find((p) => p.id === hoveredId);
		if (mn)
			return {
				cx: mn.cx,
				cy: mn.cy - mn.r - 4,
				title: mn.name,
				sub: isRetrograde(mn.tiltDeg)
					? `${kmLabel(mn.aRp)} · ${m.planetary_system_retrograde()}`
					: kmLabel(mn.aRp)
			};
		if (hoveredRings && ringBand && system.rings)
			return {
				cx: ringBand.x + ringBand.width / 2,
				cy: 50,
				title: m.tab_rings(),
				sub: `${kmLabel(system.rings.innerRp)}–${kmLabel(system.rings.outerRp)}`
			};
		return null;
	});

	// Touch: drag-to-scrub previews tooltips while a tap still navigates, matching
	// the Solar System map and the sphere lineup.
	let svgEl = $state<SVGSVGElement | null>(null);
	let downX: number | null = null;
	let downY = 0;
	let scrubbing = false;

	function clearHover() {
		hoveredId = null;
		hoveredRings = false;
	}

	function scrubAt(clientX: number, clientY: number) {
		if (!svgEl) return;
		const rect = svgEl.getBoundingClientRect();
		if (!rect.width || !rect.height) return;
		const vx = ((clientX - rect.left) / rect.width) * VIEW_W;
		const vy = ((clientY - rect.top) / rect.height) * VIEW_H;
		for (const mn of placed) {
			if (Math.hypot(vx - mn.cx, vy - mn.cy) <= mn.r + HIT_MARGIN) {
				hoveredId = mn.id;
				hoveredRings = false;
				return;
			}
		}
		if (ringBand && vx >= ringBand.x && vx <= ringBand.x + ringBand.width) {
			hoveredRings = true;
			hoveredId = null;
			return;
		}
		if (Math.hypot(vx - planetCx, vy - CY) <= planetR) {
			hoveredId = system.planet.data.id;
			hoveredRings = false;
			return;
		}
		clearHover();
	}

	function onScrubDown(e: PointerEvent) {
		if (e.pointerType === 'mouse') return;
		downX = e.clientX;
		downY = e.clientY;
		scrubbing = false;
	}

	function onScrubMove(e: PointerEvent) {
		if (e.pointerType === 'mouse' || downX === null) return;
		if (!scrubbing && Math.hypot(e.clientX - downX, e.clientY - downY) < DRAG_SLOP) return;
		scrubbing = true;
		scrubAt(e.clientX, e.clientY);
	}

	function endScrub() {
		if (scrubbing) clearHover();
		downX = null;
		scrubbing = false;
	}
</script>

<div
	class={isBackground
		? 'pointer-events-none h-full w-full overflow-hidden'
		: 'bg-muted/30 relative w-full overflow-hidden rounded-md'}
	bind:clientWidth={containerW}
>
	<svg
		bind:this={svgEl}
		viewBox={isBackground ? BG_VIEW : `0 0 ${VIEW_W} ${VIEW_H}`}
		preserveAspectRatio={isBackground ? 'xMinYMid slice' : 'xMidYMid meet'}
		class="text-muted-foreground block w-full touch-pan-y {isBackground ? 'h-full' : 'h-auto'}"
		role="group"
		aria-label={ariaLabel}
		onpointerdown={onScrubDown}
		onpointermove={onScrubMove}
		onpointerup={endScrub}
		onpointercancel={endScrub}
		onpointerleave={endScrub}
		data-vaul-no-drag
	>
		<defs>
			<!-- Limb darkening of the primary's own tint, matching how the Solar
			     System map frames the Sun: only the outer edge of this gradient is on
			     screen, so the darkening is what gives the sliver its curve. -->
			<radialGradient
				id="psmap-planet"
				gradientUnits="userSpaceOnUse"
				cx={planetCx}
				cy={CY}
				r={planetR}
			>
				<stop offset="0%" stop-color={system.planetColor} stop-opacity="1" />
				<stop
					offset={Math.max(0, 1 - PLANET_RIM / planetR)}
					stop-color={system.planetColor}
					stop-opacity="0.85"
				/>
				<stop offset="100%" stop-color={system.planetColor} stop-opacity="0.35" />
			</radialGradient>
			<pattern id="psmap-ring" width="8" height="8" patternUnits="userSpaceOnUse">
				<circle cx="2" cy="2" r="0.8" fill="currentColor" opacity="0.5" />
				<circle cx="6" cy="5.5" r="0.8" fill="currentColor" opacity="0.5" />
			</pattern>
		</defs>

		<!-- Axis: faint gridlines + log ticks in primary radii along the top. -->
		{#if !isBackground}
			{#each ticks as t (t)}
				<line
					x1={xOf(t)}
					x2={xOf(t)}
					y1="20"
					y2={VIEW_H - 20}
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
			<text
				x={X_RIGHT}
				y={VIEW_H - 8}
				text-anchor="end"
				font-size="14"
				fill="currentColor"
				opacity="0.65"
			>
				{m.planetary_system_axis_unit()}
			</text>
		{/if}

		<!-- Rings: a band across the radii they span, behind the moons that share
		     them. Links to the primary's Rings tab like a belt links to its group. -->
		{#if ringBand}
			{#snippet ringDots()}
				<rect
					x={ringBand.x}
					y="30"
					width={ringBand.width}
					height={VIEW_H - 58}
					fill="url(#psmap-ring)"
					class="text-amber-200/80"
				/>
			{/snippet}
			{#if isBackground}
				{@render ringDots()}
			{:else}
				<a
					href={focusHref(appState, system.planet.data.id, system.planetName, 'rings')}
					onclick={focusClick(focusObject, system.planet.data.id, system.planetName, {
						tab: 'rings'
					})}
					onpointerenter={() => (hoveredRings = true)}
					onpointerleave={() => (hoveredRings = false)}
					onfocus={() => (hoveredRings = true)}
					onblur={() => (hoveredRings = false)}
					aria-label={m.tab_rings()}
				>
					{@render ringDots()}
					<rect
						x={ringBand.x}
						y="30"
						width={ringBand.width}
						height={VIEW_H - 58}
						fill="transparent"
					/>
					<text
						x={ringBand.x + ringBand.width / 2}
						y={VIEW_H - 8}
						text-anchor="middle"
						font-size="18"
						class="fill-amber-200/90 font-semibold"
					>
						{m.tab_rings()}
					</text>
				</a>
			{/if}
		{/if}

		<!-- The primary, framed so only its lit right limb shows, tilted into the
		     baseline the moons sit on. A focus link like every moon. -->
		{#snippet planetDisc()}
			<circle cx={planetCx} cy={CY} r={planetR} fill="url(#psmap-planet)" />
		{/snippet}
		{#if isBackground}
			{@render planetDisc()}
		{:else}
			<a
				href={focusHref(appState, system.planet.data.id, system.planetName)}
				onclick={focusClick(focusObject, system.planet.data.id, system.planetName)}
				onpointerenter={() => (hoveredId = system.planet.data.id)}
				onpointerleave={() => hoveredId === system.planet.data.id && (hoveredId = null)}
				onfocus={() => (hoveredId = system.planet.data.id)}
				onblur={() => hoveredId === system.planet.data.id && (hoveredId = null)}
				aria-label={system.planetName}
			>
				{@render planetDisc()}
			</a>
		{/if}

		<!-- Moons: each a focus link (middle/⌘-click opens the real URL). -->
		{#each placed as mn (mn.id)}
			{#if isBackground}
				<circle cx={mn.cx} cy={mn.cy} r={mn.r} fill={mn.color} />
			{:else}
				<a
					href={focusHref(appState, mn.id, mn.name)}
					onclick={focusClick(focusObject, mn.id, mn.name)}
					onpointerenter={() => (hoveredId = mn.id)}
					onpointerleave={() => hoveredId === mn.id && (hoveredId = null)}
					onfocus={() => (hoveredId = mn.id)}
					onblur={() => hoveredId === mn.id && (hoveredId = null)}
					aria-label={mn.name}
				>
					{#if hoveredId === mn.id}
						<circle
							cx={mn.cx}
							cy={mn.cy}
							r={mn.r + 3.5}
							fill="none"
							stroke="currentColor"
							stroke-width="1"
							opacity="0.8"
						/>
					{/if}
					<circle cx={mn.cx} cy={mn.cy} r={mn.r} fill={mn.color} />
					<!-- Transparent hit target — the chart renders at ~0.4×, so a viewBox
				     unit is a fraction of a device pixel. -->
					<circle cx={mn.cx} cy={mn.cy} r={mn.r + HIT_MARGIN} fill="transparent" />
				</a>
			{/if}
		{/each}
	</svg>

	<!-- The aspect is fixed, so a viewBox unit maps to containerW/VIEW_W px. -->
	{#if tip && !isBackground}
		<ChartTip
			cx={(tip.cx / VIEW_W) * containerW}
			cy={(tip.cy / VIEW_W) * containerW}
			{containerW}
			title={tip.title}
			sub={tip.sub}
		/>
	{/if}
</div>
