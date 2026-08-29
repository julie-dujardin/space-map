<script lang="ts" module>
	// Log distance × true relative diameter, nudged vertically by inclination — a
	// minimap that doubles as a picker: click a body to fly, a band to open what
	// it links to. The primary sits at the same scale with its right limb pinned
	// just left of the axis: a giant runs off the edge as a wall, a Pluto-sized
	// primary sits there as a whole disc.

	const VIEW_W = 720;
	const VIEW_H = 240;
	const X_LEFT = 44;
	const X_RIGHT = 700;
	const CY = 120; // baseline, raised to leave room for band labels

	const MIN_R = 2.2; // floor so small bodies stay visible dots
	const MAX_OFFSET = 84;
	const PRIMARY_LIMB_X = X_LEFT - 4;
	const PRIMARY_RIM = 10; // px of limb shading, fixed so a wall-sized primary keeps an edge

	const MOON_GAP = 4; // px between a body's top edge and its first satellite
	const MOON_SPACING = 3;

	// Hit targets are padded well beyond the dots: the chart renders at ~0.4×, so
	// a viewBox unit is a fraction of a device pixel.
	const HIT_MARGIN = 16;
	const MOON_ZONE_W = 34;
	const MOON_ZONE_PAD = 7;

	const RING_TILT = -18; // deg, a ringed body's apparent ring tilt
	const RING_FORESHORTEN = 0.42; // ry/rx

	const BAND_Y = 26;
	const BAND_H = VIEW_H - 60;

	const DRAG_SLOP = 8;

	const BAND_TONE = {
		muted: { pattern: 'text-muted-foreground', label: 'fill-muted-foreground' },
		sky: { pattern: 'text-sky-400/70', label: 'fill-sky-400' },
		amber: { pattern: 'text-amber-200/80', label: 'fill-amber-200/90' }
	} as const;
</script>

<script lang="ts">
	import { getContext } from 'svelte';
	import ChartTip from './ChartTip.svelte';
	import * as m from '$lib/paraglide/messages.js';
	import { formatDistance } from '$lib/format/distance';
	import { AU_KM } from '$lib/math/units';
	import type { AppState } from '$lib/state/app-state.svelte';
	import type { FocusObject } from '$lib/state/focusable';
	import { focusHref, focusClick } from '$lib/state/focus-link';
	import type { MapBody, MapSatellite, SystemMapModel } from './system-map';

	interface Props {
		model: SystemMapModel;
		ariaLabel: string;
		/** 'background' strips axis/labels/links/tooltips and fills+crops its box —
		 *  a static decorative diagram behind a cross-ref tile. */
		variant?: 'hero' | 'background';
	}
	let { model, ariaLabel, variant = 'hero' }: Props = $props();
	let isBackground = $derived(variant === 'background');

	const appState = getContext<AppState | undefined>('appState');
	const focusObject = getContext<FocusObject | undefined>('focusObject');
	// Gradient/pattern ids are document-global; a hero and a tile on one page
	// must not share the primary's userSpaceOnUse gradient.
	const uid = $props.id();

	let logLo = $derived(Math.log10(model.domain[0]));
	let logSpan = $derived(Math.log10(model.domain[1]) - logLo);
	function xOf(km: number): number {
		const t = (Math.log10(Math.max(km / model.unitKm, 1e-9)) - logLo) / logSpan;
		return X_LEFT + t * (X_RIGHT - X_LEFT);
	}

	function distanceLabel(km: number): string {
		return formatDistance(km / AU_KM);
	}

	interface PlacedBody extends MapBody {
		cx: number;
		cy: number;
		r: number;
	}

	function minDistance(cx: number, cy: number, placed: PlacedBody[]): number {
		let min = Infinity;
		for (const p of placed) min = Math.min(min, Math.hypot(p.cx - cx, p.cy - cy));
		return min;
	}

	// Inclination sets the vertical offset; its sign goes wherever there is more
	// room, so same-distance pairs and crowded swarms spread across the baseline
	// instead of stacking on it.
	let bodies = $derived.by<PlacedBody[]>(() => {
		const placed: PlacedBody[] = [];
		for (const b of [...model.bodies].sort((a, b) => a.aKm - b.aKm)) {
			const cx = xOf(b.aKm);
			const r = Math.max(MIN_R, b.radiusKm * model.pxPerKm);
			let cy = CY;
			if (b.tiltDeg > 0) {
				// Retrograde orbits fold back from 180°, so the offset reads "tilt away
				// from the plane" for both senses rather than running off the chart.
				const tilt = b.tiltDeg > 90 ? 180 - b.tiltDeg : b.tiltDeg;
				const offset = Math.min(tilt * model.pxPerDeg, MAX_OFFSET);
				const up = CY - offset;
				const down = CY + offset;
				cy = minDistance(cx, up, placed) >= minDistance(cx, down, placed) ? up : down;
			}
			placed.push({ ...b, cx, cy, r });
		}
		return placed;
	});

	let primaryR = $derived(model.primary.radiusKm * model.pxPerKm);
	let primaryCx = $derived(PRIMARY_LIMB_X - primaryR);

	interface PlacedSatellite extends MapSatellite {
		cx: number;
		cy: number;
		r: number;
	}
	interface MoonZone {
		parent: PlacedBody;
		moons: PlacedSatellite[];
		x: number;
		y: number;
		width: number;
		height: number;
	}
	// Satellites stack straight up from their body, largest nearest it, above
	// its rings if any. One hover/click zone covers the whole stack — the tooltip
	// reads the parent, so per-moon targets aren't needed.
	let moonZones = $derived.by<MoonZone[]>(() => {
		const out: MoonZone[] = [];
		for (const parent of bodies) {
			if (!parent.satellites?.length) continue;
			const ringTop = parent.rings ? parent.r * parent.rings.outer * RING_FORESHORTEN : 0;
			let y = parent.cy - Math.max(parent.r, ringTop) - MOON_GAP;
			const moons: PlacedSatellite[] = [];
			for (const s of [...parent.satellites].sort((a, b) => b.radiusKm - a.radiusKm)) {
				const r = Math.max(MIN_R, s.radiusKm * model.pxPerKm);
				y -= r;
				moons.push({ ...s, cx: parent.cx, cy: y, r });
				y -= r + MOON_SPACING;
			}
			const top = Math.min(...moons.map((mn) => mn.cy - mn.r));
			const bottom = Math.max(...moons.map((mn) => mn.cy + mn.r));
			out.push({
				parent,
				moons,
				x: parent.cx - MOON_ZONE_W / 2,
				y: top - MOON_ZONE_PAD,
				width: MOON_ZONE_W,
				height: bottom - top + 2 * MOON_ZONE_PAD
			});
		}
		return out;
	});

	let bands = $derived(
		model.bands.map((b) => {
			const x = xOf(b.innerKm);
			return { ...b, x, width: xOf(b.outerKm) - x };
		})
	);

	let hoveredId = $state<string | null>(null);
	let hoveredZone = $state<string | null>(null);
	let hoveredBand = $state<string | null>(null);
	let containerW = $state(0);

	interface Tip {
		cx: number; // viewBox x the tooltip centers on
		cy: number; // viewBox y the tooltip sits above
		title: string;
		sub: string;
	}
	let tip = $derived.by<Tip | null>(() => {
		if (hoveredId === model.primary.id)
			return {
				cx: Math.max(X_LEFT, primaryCx),
				cy: CY - Math.min(primaryR, CY - 40),
				title: model.primary.name,
				sub: m.planetary_system_primary()
			};
		const b = bodies.find((p) => p.id === hoveredId);
		if (b) {
			const dist = distanceLabel(b.aKm);
			return {
				cx: b.cx,
				cy: b.cy - b.r - 4,
				title: b.name,
				sub: b.tiltDeg > 90 ? `${dist} · ${m.planetary_system_retrograde()}` : dist
			};
		}
		const zone = moonZones.find((z) => z.parent.id === hoveredZone);
		if (zone) {
			const cx = zone.x + zone.width / 2;
			// Giants read as "Planet · N moons"; Earth's single Moon keeps its name.
			return zone.parent.satellitesTab
				? { cx, cy: zone.y, title: zone.parent.name, sub: `${zone.parent.satelliteCount} moons` }
				: { cx, cy: zone.y, title: zone.moons[0].name, sub: zone.parent.name };
		}
		const band = bands.find((bd) => bd.key === hoveredBand);
		if (band)
			return {
				cx: band.x + band.width / 2,
				cy: 44,
				title: band.label,
				sub: `${distanceLabel(band.innerKm)}–${distanceLabel(band.outerKm)}`
			};
		return null;
	});

	// Touch: drag-to-scrub previews tooltips (a tap still navigates/focuses),
	// mirroring BodyLineup. Mouse hover stays on the per-element pointerenter
	// handlers; we only take over once a touch drag passes DRAG_SLOP, so a tap
	// stays a tap.
	let svgEl = $state<SVGSVGElement | null>(null);
	let downX: number | null = null;
	let downY = 0;
	let scrubbing = false;

	function clearHover() {
		hoveredId = null;
		hoveredZone = null;
		hoveredBand = null;
	}

	/** Hit-test the viewBox point under the pointer, front-most first: body dots
	 *  (padded like their hit targets), then moon stacks, then bands, then the
	 *  primary. */
	function scrubAt(clientX: number, clientY: number) {
		if (!svgEl) return;
		const rect = svgEl.getBoundingClientRect();
		if (!rect.width || !rect.height) return;
		// Aspect ratios match (h-auto + xMidYMid meet), so the map is uniform.
		const vx = ((clientX - rect.left) / rect.width) * VIEW_W;
		const vy = ((clientY - rect.top) / rect.height) * VIEW_H;
		clearHover();
		for (const b of bodies) {
			if (Math.hypot(vx - b.cx, vy - b.cy) <= b.r + HIT_MARGIN) {
				hoveredId = b.id;
				return;
			}
		}
		for (const z of moonZones) {
			if (vx >= z.x && vx <= z.x + z.width && vy >= z.y && vy <= z.y + z.height) {
				hoveredZone = z.parent.id;
				return;
			}
		}
		for (const band of bands) {
			if (vx >= band.x && vx <= band.x + band.width && vy >= BAND_Y && vy <= BAND_Y + BAND_H) {
				hoveredBand = band.key;
				return;
			}
		}
		if (Math.hypot(vx - primaryCx, vy - CY) <= primaryR) hoveredId = model.primary.id;
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
	<!-- A cropped background is anchored left so it keeps the primary's limb and
	     the inner bodies rather than the empty middle of the axis. -->
	<svg
		bind:this={svgEl}
		viewBox={(isBackground && model.backgroundView) || `0 0 ${VIEW_W} ${VIEW_H}`}
		preserveAspectRatio={isBackground
			? model.backgroundFit === 'fit'
				? 'xMidYMid meet'
				: model.backgroundView
					? 'xMinYMid slice'
					: 'xMidYMid slice'
			: 'xMidYMid meet'}
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
			<!-- Limb darkening of the primary's own tint: only the outer edge is on
			     screen for a big primary, so the rim is what gives the sliver its curve. -->
			<radialGradient
				id="{uid}-primary"
				gradientUnits="userSpaceOnUse"
				cx={primaryCx}
				cy={CY}
				r={primaryR}
			>
				<stop offset="0%" stop-color={model.primary.color} stop-opacity="1" />
				<stop
					offset={Math.max(0, 1 - PRIMARY_RIM / primaryR)}
					stop-color={model.primary.color}
					stop-opacity="0.85"
				/>
				<stop offset="100%" stop-color={model.primary.color} stop-opacity="0.35" />
			</radialGradient>
			<pattern id="{uid}-band" width="9" height="9" patternUnits="userSpaceOnUse">
				<circle cx="2" cy="2" r="0.9" fill="currentColor" opacity="0.55" />
				<circle cx="6.5" cy="6" r="0.9" fill="currentColor" opacity="0.55" />
			</pattern>
		</defs>

		<!-- Axis: faint gridlines + log ticks along the top. -->
		{#if !isBackground}
			{#each model.ticks as t (t)}
				{@const x = xOf(t * model.unitKm)}
				<line
					x1={x}
					x2={x}
					y1="20"
					y2={VIEW_H - 28}
					stroke="currentColor"
					stroke-width="0.5"
					opacity="0.12"
				/>
				<text {x} y="16" text-anchor="middle" font-size="16" fill="currentColor" opacity="0.85">
					{t}
				</text>
			{/each}
			<text x={X_RIGHT} y="16" text-anchor="end" font-size="14" fill="currentColor" opacity="0.65">
				{model.axisLabel}
			</text>
		{/if}

		<!-- Bands (behind the bodies); the whole band links to its target, except
		     in the background variant where it's just texture. -->
		{#each bands as band (band.key)}
			{#snippet bandFill()}
				<rect
					x={band.x}
					y={BAND_Y}
					width={band.width}
					height={BAND_H}
					fill="url(#{uid}-band)"
					class={BAND_TONE[band.tone].pattern}
				/>
			{/snippet}
			{#if isBackground}
				{@render bandFill()}
			{:else}
				<a
					href={band.href}
					onclick={band.onclick}
					onpointerenter={() => (hoveredBand = band.key)}
					onpointerleave={() => hoveredBand === band.key && (hoveredBand = null)}
					onfocus={() => (hoveredBand = band.key)}
					onblur={() => hoveredBand === band.key && (hoveredBand = null)}
					aria-label={band.label}
				>
					{@render bandFill()}
					<text
						x={band.x + band.width / 2}
						y={VIEW_H - 8}
						text-anchor="middle"
						font-size="18"
						class="font-semibold {BAND_TONE[band.tone].label}"
					>
						{band.label}
					</text>
				</a>
			{/if}
		{/each}

		<!-- The primary: a focus link like the bodies (middle/⌘-click opens the real URL). -->
		{#snippet primaryDisc()}
			<circle cx={primaryCx} cy={CY} r={primaryR} fill="url(#{uid}-primary)" />
		{/snippet}
		{#if isBackground}
			{@render primaryDisc()}
		{:else}
			<a
				href={focusHref(appState, model.primary.id, model.primary.name)}
				onclick={focusClick(focusObject, model.primary.id, model.primary.name)}
				onpointerenter={() => (hoveredId = model.primary.id)}
				onpointerleave={() => hoveredId === model.primary.id && (hoveredId = null)}
				onfocus={() => (hoveredId = model.primary.id)}
				onblur={() => hoveredId === model.primary.id && (hoveredId = null)}
				aria-label={model.primary.name}
			>
				{@render primaryDisc()}
			</a>
		{/if}

		<!-- Ringed bodies: a tilted, foreshortened band behind the dot.
		     stroke-width is the ring thickness; radius is its mid-line. -->
		{#each bodies as b (b.id)}
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

		<!-- Bodies: each a focus link, or a plain dot in the background variant. -->
		{#each bodies as b (b.id)}
			{#if isBackground}
				<circle cx={b.cx} cy={b.cy} r={b.r} fill={b.color} />
			{:else}
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
					<circle cx={b.cx} cy={b.cy} r={b.r} fill={b.color} />
					<circle cx={b.cx} cy={b.cy} r={b.r + HIT_MARGIN} fill="transparent" />
				</a>
			{/if}
		{/each}

		<!-- Moon stacks: dots, a per-body hover highlight, and one hit zone per
		     stack. The zone links to the moons tab, or to the moon itself when the
		     body has too few moons for a tab (Earth). -->
		{#each moonZones as z (z.parent.id)}
			{#if !isBackground && hoveredZone === z.parent.id}
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
			{#each z.moons as mn (mn.id)}
				<circle cx={mn.cx} cy={mn.cy} r={mn.r} fill={mn.color} />
			{/each}
			{#if !isBackground}
				{@const p = z.parent}
				{@const first = z.moons[0]}
				<a
					href={p.satellitesTab
						? focusHref(appState, p.id, p.name, 'members')
						: focusHref(appState, first.id, first.name)}
					onclick={p.satellitesTab
						? focusClick(focusObject, p.id, p.name, { tab: 'members' })
						: focusClick(focusObject, first.id, first.name)}
					onpointerenter={() => (hoveredZone = p.id)}
					onpointerleave={() => hoveredZone === p.id && (hoveredZone = null)}
					onfocus={() => (hoveredZone = p.id)}
					onblur={() => hoveredZone === p.id && (hoveredZone = null)}
					aria-label={p.satellitesTab ? `${p.name} moons` : first.name}
				>
					<rect x={z.x} y={z.y} width={z.width} height={z.height} fill="transparent" />
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
