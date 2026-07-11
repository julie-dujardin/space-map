<script lang="ts">
	import { scaleLog } from 'd3-scale';
	import * as m from '$lib/paraglide/messages.js';
	import {
		SAT_ORBIT_ZONES,
		FOCUS_COLORS,
		GEO_ALT_KM,
		CLASS_SLUG_PREFIX,
		classNameFromSlug,
		orbitClassLabel,
		type EarthOrbitSample,
		type OrbitZone,
		type ZonePoint
	} from '$lib/charts/orbit-zones';

	interface Props {
		samples: EarthOrbitSample[];
		focusedSlug: string;
		populationBySlug: Record<string, number>;
		onZoneClick: (slug: string) => void;
		height?: number;
	}

	let { samples, focusedSlug, populationBySlug, onZoneClick, height = 280 }: Props = $props();

	const M = { top: 8, right: 10, bottom: 36, left: 52 };
	let width = $state(0);
	let innerW = $derived(Math.max(0, width - M.left - M.right));
	let innerH = $derived(Math.max(0, height - M.top - M.bottom));

	let focusedClass = $derived(classNameFromSlug(focusedSlug));
	let focusedZone = $derived<OrbitZone | null>(
		focusedClass ? (SAT_ORBIT_ZONES[focusedClass] ?? null) : null
	);

	// Single domain that fits every zone (LEO → cislunar+VHEO) on log axes.
	const domain = { x: [100, 2_000_000] as const, y: [100, 2_000_000] as const };

	let xScale = $derived(
		scaleLog()
			.domain([...domain.x])
			.range([0, innerW])
			.clamp(true)
	);
	let yScale = $derived(
		scaleLog()
			.domain([...domain.y])
			.range([innerH, 0])
			.clamp(true)
	);

	function polyPath(poly: ZonePoint[]): string {
		if (poly.length === 0) return '';
		return (
			poly
				.map((p, i) => `${i === 0 ? 'M' : 'L'}${xScale(p.x).toFixed(2)},${yScale(p.y).toFixed(2)}`)
				.join(' ') + 'Z'
		);
	}

	function isFocused(s: EarthOrbitSample): boolean {
		if (focusedClass == null) return false;
		return s.classes.includes(focusedClass);
	}

	let visibleSamples = $derived(samples.filter((s) => s.perigee_km >= 50 && s.apogee_km >= 50));

	let backgroundDots = $derived(visibleSamples.filter((s) => !isFocused(s)));
	let focusedDots = $derived(visibleSamples.filter((s) => isFocused(s)));

	// Powers of ten — d3's default log tick set crowds at low magnitudes.
	const TICKS = [100, 1000, 10000, 100000, 1000000];

	function formatTick(v: number): string {
		if (v >= 1_000_000) return `${v / 1_000_000}M`;
		if (v >= 1000) return `${v / 1000}k`;
		return `${v}`;
	}

	// peri = apo (circular orbit) diagonal.
	let diag = $derived({
		x1: xScale(domain.x[0]),
		y1: yScale(domain.x[0]),
		x2: xScale(Math.min(domain.x[1], domain.y[1])),
		y2: yScale(Math.min(domain.x[1], domain.y[1]))
	});

	let geoX = $derived(xScale(GEO_ALT_KM));
	let geoY = $derived(yScale(GEO_ALT_KM));
	let geoInRange = $derived(GEO_ALT_KM >= domain.x[0] && GEO_ALT_KM <= domain.x[1]);

	let plotZones = $derived(Object.values(SAT_ORBIT_ZONES).filter((z) => z.polygon.length > 0));

	type Tip = { kind: 'zone'; zone: OrbitZone };
	let tip = $state<Tip | null>(null);
	let mouse = $state({ x: 0, y: 0 });
	let containerEl = $state<HTMLDivElement | null>(null);

	function handleMove(e: MouseEvent) {
		if (!containerEl) return;
		const rect = containerEl.getBoundingClientRect();
		mouse = { x: e.clientX - rect.left, y: e.clientY - rect.top };
	}

	function zonePopulation(className: string): number {
		return populationBySlug[`${CLASS_SLUG_PREFIX}${className}`] ?? 0;
	}

	let focusedIsIncOnly = $derived(focusedZone != null && focusedZone.polygon.length === 0);
	const focusedColor = FOCUS_COLORS['peri-apo'];

	// Touch: drag-to-scrub previews the zone tooltip (a tap still navigates),
	// mirroring SolarSystemMap. Mouse hover stays on the per-element handlers; we
	// only take over once a touch drag passes DRAG_SLOP, so a tap stays a tap.
	const DRAG_SLOP = 8;
	let downX: number | null = null;
	let downY = 0;
	let scrubbing = false;

	/** Point-in-polygon (ray cast) in screen px against a zone outline. */
	function pointInZone(px: number, py: number, poly: ZonePoint[]): boolean {
		let inside = false;
		for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
			const xi = xScale(poly[i].x);
			const yi = yScale(poly[i].y);
			const xj = xScale(poly[j].x);
			const yj = yScale(poly[j].y);
			if (yi > py !== yj > py && px < ((xj - xi) * (py - yi)) / (yj - yi) + xi) inside = !inside;
		}
		return inside;
	}

	function scrubAt(clientX: number, clientY: number) {
		if (!containerEl) return;
		const rect = containerEl.getBoundingClientRect();
		mouse = { x: clientX - rect.left, y: clientY - rect.top };
		const x = mouse.x - M.left; // into the inner plot (after the g translate)
		const y = mouse.y - M.top;
		for (const z of plotZones) {
			if (pointInZone(x, y, z.polygon)) {
				tip = { kind: 'zone', zone: z };
				return;
			}
		}
		tip = null;
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
		if (scrubbing) tip = null;
		downX = null;
		scrubbing = false;
	}
</script>

<div
	class="relative w-full touch-pan-y"
	bind:this={containerEl}
	bind:clientWidth={width}
	style:height="{height}px"
	onmousemove={handleMove}
	onmouseleave={() => (tip = null)}
	onpointerdown={onScrubDown}
	onpointermove={onScrubMove}
	onpointerup={endScrub}
	onpointercancel={endScrub}
	onpointerleave={endScrub}
	data-vaul-no-drag
	role="group"
	aria-label={m.scatter_membership_title()}
>
	{#if width > 0}
		<svg {width} {height} viewBox="0 0 {width} {height}" class="block">
			<g transform="translate({M.left},{M.top})">
				<rect width={innerW} height={innerH} class="fill-muted/10" />

				<!-- peri = apo diagonal (circular-orbit locus). -->
				<line
					x1={diag.x1}
					y1={diag.y1}
					x2={diag.x2}
					y2={diag.y2}
					class="stroke-muted-foreground/30"
					stroke-dasharray="3 3"
					stroke-width="1"
				/>

				{#if geoInRange}
					<line
						x1={geoX}
						x2={geoX}
						y1={0}
						y2={innerH}
						class="stroke-muted-foreground/30"
						stroke-dasharray="2 4"
						stroke-width="1"
					/>
					<line
						x1={0}
						x2={innerW}
						y1={geoY}
						y2={geoY}
						class="stroke-muted-foreground/30"
						stroke-dasharray="2 4"
						stroke-width="1"
					/>
				{/if}

				{#each plotZones as z (z.className)}
					{@const focused = focusedClass === z.className}
					<path
						role="button"
						tabindex="0"
						aria-label={z.className}
						d={polyPath(z.polygon)}
						class="cursor-pointer transition-opacity focus:outline-none focus-visible:stroke-2"
						fill={focused ? focusedColor : 'transparent'}
						fill-opacity={focused ? 0.22 : 0}
						stroke={focused ? focusedColor : 'var(--color-muted-foreground)'}
						stroke-opacity={focused ? 1 : 0.4}
						stroke-width={focused ? 1.5 : 1}
						onmouseenter={() => (tip = { kind: 'zone', zone: z })}
						onclick={() => onZoneClick(`${CLASS_SLUG_PREFIX}${z.className}`)}
						onkeydown={(e) => {
							if (e.key === 'Enter' || e.key === ' ') {
								e.preventDefault();
								onZoneClick(`${CLASS_SLUG_PREFIX}${z.className}`);
							}
						}}
					/>
				{/each}

				{#each backgroundDots as s, i (i + '|' + s.name)}
					{@const cx = xScale(s.perigee_km)}
					{@const cy = yScale(s.apogee_km)}
					<circle {cx} {cy} r={1.4} class="fill-foreground/25 pointer-events-none" />
				{/each}

				{#each focusedDots as s, i (i + '|' + s.name)}
					{@const cx = xScale(s.perigee_km)}
					{@const cy = yScale(s.apogee_km)}
					<circle {cx} {cy} r={2} fill={focusedColor} class="pointer-events-none" />
				{/each}

				<!-- Border on top — masks zone strokes at the chart edges. -->
				<rect width={innerW} height={innerH} fill="none" class="stroke-border" stroke-width="1" />

				<g transform="translate(0,{innerH})">
					<line x2={innerW} class="stroke-muted-foreground/60" />
					{#each TICKS as t (t)}
						{@const tx = xScale(t)}
						<g transform="translate({tx},0)">
							<line y2={3} class="stroke-muted-foreground/60" />
							<text y={12} text-anchor="middle" class="fill-muted-foreground" style:font-size="9px">
								{formatTick(t)}
							</text>
						</g>
					{/each}
					<text
						x={innerW / 2}
						y={M.bottom - 4}
						text-anchor="middle"
						class="fill-muted-foreground"
						style:font-size="9px"
					>
						{m.scatter_axis_perigee()}
					</text>
				</g>
				<g>
					<line y2={innerH} class="stroke-muted-foreground/60" />
					{#each TICKS as t (t)}
						{@const ty = yScale(t)}
						<g transform="translate(0,{ty})">
							<line x2={-3} class="stroke-muted-foreground/60" />
							<text
								x={-5}
								dy={3}
								text-anchor="end"
								class="fill-muted-foreground"
								style:font-size="9px"
							>
								{formatTick(t)}
							</text>
						</g>
					{/each}
					<text
						transform="translate({-M.left + 10},{innerH / 2}) rotate(-90)"
						text-anchor="middle"
						class="fill-muted-foreground"
						style:font-size="9px"
					>
						{m.scatter_axis_apogee()}
					</text>
				</g>
			</g>
		</svg>
	{/if}

	{#if focusedIsIncOnly && focusedZone}
		<!-- Inc-only zones have no polygon — surface the rule as a top banner. -->
		<div
			class="bg-muted/70 text-muted-foreground absolute top-1 right-2 left-14 rounded px-1.5 py-0.5 leading-tight"
			style:font-size="9px"
		>
			{focusedZone.tooltipDefinition()}
		</div>
	{/if}

	{#if tip}
		<div
			class="bg-popover text-popover-foreground border-border pointer-events-none absolute z-50 rounded-md border px-2 py-1 text-xs shadow-md"
			style:left="{Math.min(mouse.x + 10, width - 200)}px"
			style:top="{Math.max(0, mouse.y - 8)}px"
			style:max-width="260px"
		>
			<div class="font-semibold">{orbitClassLabel(tip.zone.className)}</div>
			<div class="text-muted-foreground mt-0.5 whitespace-normal">
				{tip.zone.tooltipDefinition()}
			</div>
			<div class="text-muted-foreground mt-0.5 tabular-nums">
				{m.scatter_tooltip_population({ count: zonePopulation(tip.zone.className) })}
			</div>
		</div>
	{/if}
</div>
