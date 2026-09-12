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
		type OrbitZone
	} from '$lib/charts/orbit-zones';
	import { pointInZone, polyPath, zonePopulation } from '$lib/charts/zone-geometry';
	import { createScrub } from '$lib/charts/scrub';
	import ScatterAxes from './ScatterAxes.svelte';

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

	let focusedIsIncOnly = $derived(focusedZone != null && focusedZone.polygon.length === 0);
	const focusedColor = FOCUS_COLORS['peri-apo'];

	function scrubAt(clientX: number, clientY: number) {
		if (!containerEl) return;
		const rect = containerEl.getBoundingClientRect();
		mouse = { x: clientX - rect.left, y: clientY - rect.top };
		const x = mouse.x - M.left; // into the inner plot (after the g translate)
		const y = mouse.y - M.top;
		for (const z of plotZones) {
			if (pointInZone(x, y, z.polygon, xScale, yScale)) {
				tip = { kind: 'zone', zone: z };
				return;
			}
		}
		tip = null;
	}

	const scrub = createScrub({ onScrub: scrubAt, onEnd: () => (tip = null) });
</script>

<div
	class="relative w-full touch-pan-y"
	bind:this={containerEl}
	bind:clientWidth={width}
	style:height="{height}px"
	onmousemove={handleMove}
	onmouseleave={() => (tip = null)}
	{...scrub}
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
						d={polyPath(z.polygon, xScale, yScale)}
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

				<ScatterAxes
					{innerW}
					{innerH}
					marginLeft={M.left}
					marginBottom={M.bottom}
					{xScale}
					{yScale}
					xTicks={TICKS}
					yTicks={TICKS}
					{formatTick}
					xLabel={m.scatter_axis_perigee()}
					yLabel={m.scatter_axis_apogee()}
				/>
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
			class="bg-foreground text-background pointer-events-none absolute z-50 -translate-y-full rounded-md px-2 py-1 text-xs shadow-md"
			style:left="{Math.min(mouse.x + 10, width - 200)}px"
			style:top="{mouse.y - 10}px"
			style:max-width="260px"
		>
			<div class="font-semibold">{orbitClassLabel(tip.zone.className)}</div>
			<div class="text-background/70 mt-0.5 whitespace-normal">
				{tip.zone.tooltipDefinition()}
			</div>
			<div class="text-background/70 mt-0.5 tabular-nums">
				{m.scatter_tooltip_population({
					count: zonePopulation(populationBySlug, tip.zone.className)
				})}
			</div>
		</div>
	{/if}
</div>
