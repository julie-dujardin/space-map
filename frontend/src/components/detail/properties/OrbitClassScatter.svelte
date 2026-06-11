<script lang="ts">
	import { scaleLinear } from 'd3-scale';
	import * as m from '$lib/paraglide/messages.js';
	import { formatNumber } from '$lib/format/quantities';
	import {
		ORBIT_ZONES,
		PLANET_A_REFS,
		NEO_CLASSES,
		CLASS_SLUG_PREFIX,
		FLAG_SLUG_PREFIX,
		FOCUS_COLORS,
		classNameFromSlug,
		orbitClassLabel,
		type OrbitSample,
		type OrbitZone,
		type PlotType,
		type ZonePoint
	} from '$lib/charts/orbit-zones';

	interface Props {
		samples: OrbitSample[];
		focusedSlug: string;
		plotType: PlotType;
		/** Per-class real population, sourced from groups/__index__.json `n` field. */
		populationBySlug: Record<string, number>;
		onZoneClick: (slug: string) => void;
		height?: number;
	}

	let {
		samples,
		focusedSlug,
		plotType,
		populationBySlug,
		onZoneClick,
		height = 240
	}: Props = $props();

	const M = { top: 8, right: 10, bottom: 36, left: 44 };
	let width = $state(0); // measured at runtime from the wrapping div
	let innerW = $derived(Math.max(0, width - M.left - M.right));
	let innerH = $derived(Math.max(0, height - M.top - M.bottom));

	let focusedZones = $derived.by<OrbitZone[]>(() => {
		if (focusedSlug === `${FLAG_SLUG_PREFIX}neo` || focusedSlug === `${FLAG_SLUG_PREFIX}pha`) {
			return NEO_CLASSES.map((n) => ORBIT_ZONES[n]).filter(Boolean);
		}
		const cls = classNameFromSlug(focusedSlug);
		if (!cls) return [];
		const z = ORBIT_ZONES[cls];
		return z ? [z] : [];
	});

	let focusedClassNames = $derived(new Set(focusedZones.map((z) => z.className)));

	let plotZones = $derived(Object.values(ORBIT_ZONES).filter((z) => z.plotType === plotType));

	// Two presets for a-q so TNO/CEN are reachable without making the inner
	// zones invisible. The chart auto-picks based on what's focused; user can
	// override with the toggle.
	const DOMAIN_PRESETS = {
		'a-q': {
			// Inner cuts off right before centaurs (a = 5.5 AU).
			inner: { x: [0, 5.5] as [number, number], y: [0, 5] as [number, number] },
			outer: { x: [0, 100] as [number, number], y: [0, 60] as [number, number] }
		},
		'q-e': { x: [0, 3] as [number, number], y: [0, 12] as [number, number] }
	};

	let userRange = $state<'inner' | 'outer' | null>(null);
	let autoRange = $derived.by<'inner' | 'outer'>(() => {
		if (plotType !== 'a-q') return 'inner';
		for (const z of focusedZones) {
			for (const p of z.polygon) {
				if (p.x > 6) return 'outer';
			}
		}
		return 'inner';
	});
	let range = $derived<'inner' | 'outer'>(userRange ?? autoRange);
	let domain = $derived(plotType === 'a-q' ? DOMAIN_PRESETS['a-q'][range] : DOMAIN_PRESETS['q-e']);

	let xScale = $derived(scaleLinear().domain(domain.x).range([0, innerW]));
	let yScale = $derived(scaleLinear().domain(domain.y).range([innerH, 0]));

	function sampleX(s: OrbitSample): number | null {
		if (plotType === 'a-q') return s.a;
		return s.e;
	}

	function polyPath(poly: ZonePoint[]): string {
		if (poly.length === 0) return '';
		return (
			poly
				.map((p, i) => `${i === 0 ? 'M' : 'L'}${xScale(p.x).toFixed(2)},${yScale(p.y).toFixed(2)}`)
				.join(' ') + 'Z'
		);
	}

	function isFocused(s: OrbitSample): boolean {
		if (focusedSlug === `${FLAG_SLUG_PREFIX}neo`) return s.neo;
		if (focusedSlug === `${FLAG_SLUG_PREFIX}pha`) return s.pha;
		const cls = classNameFromSlug(focusedSlug);
		return cls != null && s.slug === `${CLASS_SLUG_PREFIX}${cls}`;
	}

	let visibleSamples = $derived(
		(samples ?? []).filter((s) => {
			const sx = sampleX(s);
			if (sx == null || !Number.isFinite(sx)) return false;
			return true;
		})
	);

	// Render order: background dots → focused dots → PHA on top
	let backgroundDots = $derived(visibleSamples.filter((s) => !isFocused(s) && !s.pha));
	let focusedDots = $derived(visibleSamples.filter((s) => isFocused(s) && !s.pha));
	let phaDots = $derived(visibleSamples.filter((s) => s.pha));

	let xTicks = $derived(xScale.ticks(6));
	let yTicks = $derived(yScale.ticks(6));

	let focusedColor = $derived(FOCUS_COLORS[plotType]);

	function formatTick(v: number): string {
		if (v === 0) return '0';
		if (Math.abs(v) >= 10) return v.toFixed(0);
		if (Math.abs(v) >= 1) return v.toFixed(1);
		return v.toFixed(2);
	}

	// Tooltip — single floating div, mouse-positioned.
	type Tip = { kind: 'zone'; zone: OrbitZone } | { kind: 'sample'; sample: OrbitSample };
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

	function zoneClassLabel(z: OrbitZone): string {
		return orbitClassLabel(z.className);
	}
</script>

<div
	class="relative w-full"
	bind:this={containerEl}
	bind:clientWidth={width}
	style:height="{height}px"
	onmousemove={handleMove}
	onmouseleave={() => (tip = null)}
	role="img"
>
	{#if width > 0}
		<svg {width} {height} viewBox="0 0 {width} {height}" class="block">
			<g transform="translate({M.left},{M.top})">
				<rect width={innerW} height={innerH} class="fill-muted/10" />

				{#if plotType === 'a-q'}
					<!-- q = a diagonal: physical limit (circular orbit, e=0) -->
					{@const x1 = xScale(Math.max(domain.x[0], domain.y[0]))}
					{@const y1 = yScale(Math.max(domain.x[0], domain.y[0]))}
					{@const x2 = xScale(Math.min(domain.x[1], domain.y[1]))}
					{@const y2 = yScale(Math.min(domain.x[1], domain.y[1]))}
					<line
						{x1}
						{y1}
						{x2}
						{y2}
						class="stroke-muted-foreground/30"
						stroke-dasharray="3 3"
						stroke-width="1"
					/>

					<!-- Planet reference lines. Labels suppressed — inner-planet a's
				     ( Mercury/Venus/Earth ~0.4–1.0 AU) are too tightly packed for
				     legible text at this width. -->
					{#each PLANET_A_REFS as p (p.name)}
						{@const px = xScale(p.a)}
						{#if px >= 0 && px <= innerW}
							<line
								x1={px}
								x2={px}
								y1={0}
								y2={innerH}
								class="stroke-muted-foreground/30"
								stroke-dasharray="2 4"
								stroke-width="1"
							/>
						{/if}
					{/each}
				{/if}

				<!-- Approximate PHA "danger band": q ≈ 1 AU ± 0.05 (Earth-MOID proxy) -->
				{#if plotType === 'a-q' && (focusedSlug === `${FLAG_SLUG_PREFIX}neo` || focusedSlug === `${FLAG_SLUG_PREFIX}pha`)}
					{@const bandY1 = yScale(Math.min(1.05, domain.y[1]))}
					{@const bandY2 = yScale(Math.max(0.95, domain.y[0]))}
					<rect
						x={0}
						y={Math.min(bandY1, bandY2)}
						width={innerW}
						height={Math.abs(bandY2 - bandY1)}
						class="fill-red-500/15"
					/>
					<line
						x1={0}
						x2={innerW}
						y1={yScale(1.0)}
						y2={yScale(1.0)}
						class="stroke-red-500/60"
						stroke-dasharray="4 3"
						stroke-width="1"
					/>
				{/if}

				<!-- Zone polygons -->
				{#each plotZones as z (z.className)}
					{@const focused = focusedClassNames.has(z.className)}
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

				<!-- Background dots (non-focused) -->
				{#each backgroundDots as s (s.name + s.slug)}
					{@const cx = xScale(sampleX(s) as number)}
					{@const cy = yScale(s.q)}
					<circle {cx} {cy} r={1.4} class="fill-foreground/25 pointer-events-none" />
				{/each}

				<!-- Focused dots -->
				{#each focusedDots as s (s.name + s.slug)}
					{@const cx = xScale(sampleX(s) as number)}
					{@const cy = yScale(s.q)}
					<circle
						role="img"
						aria-label={s.name}
						{cx}
						{cy}
						r={1.8}
						fill={focusedColor}
						onmouseenter={() => (tip = { kind: 'sample', sample: s })}
					/>
				{/each}

				<!-- PHA dots, always red, drawn on top -->
				{#each phaDots as s (s.name + s.slug)}
					{@const cx = xScale(sampleX(s) as number)}
					{@const cy = yScale(s.q)}
					<circle
						role="img"
						aria-label={s.name}
						{cx}
						{cy}
						r={2}
						class="fill-red-500"
						onmouseenter={() => (tip = { kind: 'sample', sample: s })}
					/>
				{/each}

				<!-- Border on top: masks zone-polygon strokes that lie along the
				     chart edge (AST/COM catch-alls, IEO/ATE/APO bottoms at q=0, …). -->
				<rect width={innerW} height={innerH} fill="none" class="stroke-border" stroke-width="1" />

				<!-- Axes -->
				<g transform="translate(0,{innerH})">
					<line x2={innerW} class="stroke-muted-foreground/60" />
					{#each xTicks as t (t)}
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
						{plotType === 'a-q' ? m.scatter_axis_a() : m.scatter_axis_e()}
					</text>
				</g>
				<g>
					<line y2={innerH} class="stroke-muted-foreground/60" />
					{#each yTicks as t (t)}
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
						{m.scatter_axis_q()}
					</text>
				</g>
			</g>
		</svg>
	{/if}

	{#if plotType === 'a-q'}
		<div
			class="text-muted-foreground absolute top-1 left-9 flex gap-0 overflow-hidden rounded border border-border"
			style:font-size="9px"
		>
			<button
				type="button"
				class="px-1.5 py-0.5 transition-colors"
				class:bg-foreground={range === 'inner'}
				class:text-background={range === 'inner'}
				onclick={() => (userRange = 'inner')}
			>
				{m.scatter_range_inner()}
			</button>
			<button
				type="button"
				class="px-1.5 py-0.5 transition-colors"
				class:bg-foreground={range === 'outer'}
				class:text-background={range === 'outer'}
				onclick={() => (userRange = 'outer')}
			>
				{m.scatter_range_outer()}
			</button>
		</div>
	{/if}

	{#if tip}
		<div
			class="bg-popover text-popover-foreground border-border pointer-events-none absolute z-50 rounded-md border px-2 py-1 text-xs shadow-md"
			style:left="{Math.min(mouse.x + 10, width - 180)}px"
			style:top="{Math.max(0, mouse.y - 8)}px"
			style:max-width="240px"
		>
			{#if tip.kind === 'zone'}
				<div class="font-semibold">{zoneClassLabel(tip.zone)}</div>
				<div class="text-muted-foreground mt-0.5 whitespace-normal">
					{tip.zone.tooltipDefinition()}
				</div>
				<div class="text-muted-foreground mt-0.5 tabular-nums">
					{m.scatter_tooltip_population({ count: zonePopulation(tip.zone.className) })}
				</div>
			{:else}
				<div class="font-semibold">{tip.sample.name}</div>
				<div class="text-muted-foreground tabular-nums">
					a={tip.sample.a == null ? '—' : formatNumber(tip.sample.a)} · e={formatNumber(
						tip.sample.e
					)}
					· q={formatNumber(tip.sample.q)}
				</div>
				{#if tip.sample.pha}
					<div class="font-semibold text-red-500">{m.scatter_tooltip_pha()}</div>
				{:else if tip.sample.neo}
					<div class="text-orange-400">{m.scatter_tooltip_neo()}</div>
				{/if}
			{/if}
		</div>
	{/if}
</div>
