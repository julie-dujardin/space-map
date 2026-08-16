<script lang="ts" module>
	import type { PlotType } from '$lib/charts/orbit-zones';

	// Last shown plot, recorded at module level because the chart briefly
	// unmounts during group navigation. Lets a click on a COM zone keep the
	// comet plot it was clicked from.
	let lastPlot: PlotType | null = null;
</script>

<script lang="ts">
	import { scaleLinear, scaleLog } from 'd3-scale';
	import * as m from '$lib/paraglide/messages.js';
	import { formatNumber } from '$lib/format/quantities';
	import {
		ORBIT_ZONES,
		PLANET_A_REFS,
		NEO_CLASSES,
		COMET_PLOT_TYPES,
		COMET_PLOT_CLASSES,
		AT_DOMAIN,
		QE_DOMAIN,
		CLASS_SLUG_PREFIX,
		FLAG_SLUG_PREFIX,
		FOCUS_COLORS,
		classNameFromSlug,
		orbitClassLabel,
		tisserand,
		type OrbitSample,
		type OrbitZone,
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

	const uid = $props.id();

	// Top margin leaves room for the range/plot switcher overlay.
	const M = { top: 26, right: 10, bottom: 36, left: 44 };
	let width = $state(0); // measured at runtime from the wrapping div
	let innerW = $derived(Math.max(0, width - M.left - M.right));
	let innerH = $derived(Math.max(0, height - M.top - M.bottom));

	// Comet classes live on two switchable plots (families on a-T, unbound
	// trajectories on q-e); `plotType` is the auto pick for the focused class,
	// the toggle lets the user flip.
	let isCometMode = $derived(COMET_PLOT_TYPES.includes(plotType));
	let userPlot = $state<PlotType | null>(null);
	let activePlot = $derived(isCometMode ? (userPlot ?? plotType) : plotType);

	let focusedZones = $derived.by<OrbitZone[]>(() => {
		if (focusedSlug === `${FLAG_SLUG_PREFIX}neo` || focusedSlug === `${FLAG_SLUG_PREFIX}pha`) {
			return NEO_CLASSES.map((n) => ORBIT_ZONES[n]).filter(Boolean);
		}
		const cls = classNameFromSlug(focusedSlug);
		if (!cls) return [];
		// A class can have a zone on several plots (e.g. COM on q-e and a-T).
		return Object.values(ORBIT_ZONES).filter((z) => z.className === cls);
	});

	let focusedClassNames = $derived(new Set(focusedZones.map((z) => z.className)));

	// Inc-only classes (HYA: hyperbolic, no plottable a) carry no polygon; they
	// fold in below the map as chips instead of drawing a zone here.
	let plotZones = $derived(
		Object.values(ORBIT_ZONES).filter((z) => z.plotType === activePlot && z.polygon.length > 0)
	);

	// Two presets for a-q so TNO/CEN are reachable without making the inner
	// zones invisible. The chart auto-picks based on what's focused; user can
	// override with the toggle.
	const DOMAIN_PRESETS = {
		'a-q': {
			// Inner cuts off right before centaurs (a = 5.5 AU); outer picks
			// up from there.
			// y reaches past the q = a apex at 5.5 so the Trojan zone's top shows.
			inner: { x: [0, 5.5] as [number, number], y: [0, 5.5] as [number, number] },
			outer: { x: [5.5, 100] as [number, number], y: [0, 60] as [number, number] }
		},
		'q-e': QE_DOMAIN,
		'a-T': AT_DOMAIN
	};

	let userRange = $state<'inner' | 'outer' | null>(null);
	let autoRange = $derived.by<'inner' | 'outer'>(() => {
		if (activePlot !== 'a-q') return 'inner';
		for (const z of focusedZones) {
			for (const p of z.polygon) {
				if (p.x > 6) return 'outer';
			}
		}
		return 'inner';
	});
	let range = $derived<'inner' | 'outer'>(userRange ?? autoRange);

	// On focus change, reset to the new auto plot/range — except COM, which has
	// zones on both comet plots: keep whatever plot it was clicked from instead
	// of jumping to q-e. `lastPlot` holds that pre-navigation view.
	$effect(() => {
		const cls = classNameFromSlug(focusedSlug);
		if (cls === 'COM') {
			userPlot = lastPlot != null && COMET_PLOT_TYPES.includes(lastPlot) ? lastPlot : null;
		} else {
			userPlot = null;
		}
		userRange = null;
	});

	// Record the shown plot for the COM pin above. Declared after it so the
	// pin reads the pre-navigation value within the same flush.
	$effect(() => {
		lastPlot = activePlot;
	});
	let domain = $derived(
		activePlot === 'a-q'
			? DOMAIN_PRESETS['a-q'][range]
			: DOMAIN_PRESETS[activePlot as 'q-e' | 'a-T']
	);

	// a-T spans 1–60 AU; log keeps the short-period families readable.
	let xScale = $derived(
		(activePlot === 'a-T' ? scaleLog() : scaleLinear()).domain(domain.x).range([0, innerW])
	);
	let yScale = $derived(scaleLinear().domain(domain.y).range([innerH, 0]));

	/** Plot coordinates for a sample; null = not representable on this plot. */
	function samplePoint(s: OrbitSample): { x: number; y: number } | null {
		if (activePlot === 'a-q') return s.a == null ? null : { x: s.a, y: s.q };
		if (activePlot === 'q-e') return { x: s.e, y: s.q };
		if (s.a == null || s.i == null) return null;
		const t = tisserand(s.a, s.e, s.i);
		return t == null ? null : { x: s.a, y: t };
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

	type Dot = { s: OrbitSample; px: number; py: number };
	let visibleDots = $derived.by<Dot[]>(() => {
		const out: Dot[] = [];
		for (const s of samples ?? []) {
			// Comet plots only show comet-family samples; asteroid dots there
			// are clutter (e.g. the whole main belt lands inside ETc on a-T).
			if (isCometMode && !COMET_PLOT_CLASSES.has(s.slug)) continue;
			const p = samplePoint(s);
			if (!p || !Number.isFinite(p.x) || !Number.isFinite(p.y)) continue;
			out.push({ s, px: xScale(p.x), py: yScale(p.y) });
		}
		return out;
	});

	// Render order: background dots → focused dots → PHA on top
	let backgroundDots = $derived(visibleDots.filter((d) => !isFocused(d.s) && !d.s.pha));
	let focusedDots = $derived(visibleDots.filter((d) => isFocused(d.s) && !d.s.pha));
	let phaDots = $derived(visibleDots.filter((d) => d.s.pha));

	let xTicks = $derived(
		activePlot === 'a-T' ? [1, 2, 5, 10, 20, 50] : xScale.ticks(activePlot === 'q-e' ? 4 : 6)
	);
	let yTicks = $derived(yScale.ticks(6));

	let focusedColor = $derived(FOCUS_COLORS[activePlot]);

	function formatTick(v: number): string {
		if (Math.abs(v) >= 10) return v.toFixed(0);
		// Shortest exact form ≤2 decimals, so dense domains (q-e) stay distinct.
		return String(parseFloat(v.toFixed(2)));
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

	// Touch: drag-to-scrub previews the tooltip (a tap still navigates the zone),
	// mirroring SolarSystemMap. Mouse hover stays on the per-element handlers; we
	// only take over once a touch drag passes DRAG_SLOP, so a tap stays a tap.
	const DRAG_SLOP = 8;
	const TOUCH_R2 = 12 * 12; // px² pick radius around a dot, finger-sized
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

	/** Hit-test the plot point under the finger: a focused/PHA dot wins (within a
	 *  finger-sized radius), else the zone it falls in. */
	function scrubAt(clientX: number, clientY: number) {
		if (!containerEl) return;
		const rect = containerEl.getBoundingClientRect();
		mouse = { x: clientX - rect.left, y: clientY - rect.top };
		const x = mouse.x - M.left; // into the inner plot (after the g translate)
		const y = mouse.y - M.top;
		let best: OrbitSample | null = null;
		let bestD = TOUCH_R2;
		for (const d of [...phaDots, ...focusedDots]) {
			const dd = (x - d.px) ** 2 + (y - d.py) ** 2;
			if (dd <= bestD) {
				bestD = dd;
				best = d.s;
			}
		}
		if (best) {
			tip = { kind: 'sample', sample: best };
			return;
		}
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
				<clipPath id="plot-clip-{uid}">
					<rect width={innerW} height={innerH} />
				</clipPath>
				<rect width={innerW} height={innerH} class="fill-muted/10" />

				{#if activePlot === 'a-q'}
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
				{#if activePlot === 'a-q' && (focusedSlug === `${FLAG_SLUG_PREFIX}neo` || focusedSlug === `${FLAG_SLUG_PREFIX}pha`)}
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

				<g clip-path="url(#plot-clip-{uid})">
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

					{#each backgroundDots as d (d.s.name + d.s.slug)}
						<circle cx={d.px} cy={d.py} r={1.4} class="fill-foreground/25 pointer-events-none" />
					{/each}

					{#each focusedDots as d (d.s.name + d.s.slug)}
						<circle
							role="img"
							aria-label={d.s.name}
							cx={d.px}
							cy={d.py}
							r={1.8}
							fill={focusedColor}
							onmouseenter={() => (tip = { kind: 'sample', sample: d.s })}
						/>
					{/each}

					{#each phaDots as d (d.s.name + d.s.slug)}
						<circle
							role="img"
							aria-label={d.s.name}
							cx={d.px}
							cy={d.py}
							r={2}
							class="fill-red-500"
							onmouseenter={() => (tip = { kind: 'sample', sample: d.s })}
						/>
					{/each}
				</g>

				<!-- Border on top: masks zone-polygon strokes that lie along the
				     chart edge (AST/COM catch-alls, IEO/ATE/APO bottoms at q=0, …). -->
				<rect width={innerW} height={innerH} fill="none" class="stroke-border" stroke-width="1" />

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
						{activePlot === 'q-e' ? m.scatter_axis_e() : m.scatter_axis_a()}
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
						{activePlot === 'a-T' ? m.scatter_axis_T() : m.scatter_axis_q()}
					</text>
				</g>
			</g>
		</svg>
	{/if}

	{#if activePlot === 'a-q'}
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
	{:else if isCometMode}
		<div
			class="text-muted-foreground absolute top-1 left-9 flex gap-0 overflow-hidden rounded border border-border"
			style:font-size="9px"
		>
			<button
				type="button"
				class="px-1.5 py-0.5 transition-colors"
				class:bg-foreground={activePlot === 'a-T'}
				class:text-background={activePlot === 'a-T'}
				onclick={() => (userPlot = 'a-T')}
			>
				{m.scatter_plot_families()}
			</button>
			<button
				type="button"
				class="px-1.5 py-0.5 transition-colors"
				class:bg-foreground={activePlot === 'q-e'}
				class:text-background={activePlot === 'q-e'}
				onclick={() => (userPlot = 'q-e')}
			>
				{m.scatter_plot_trajectories()}
			</button>
		</div>
	{/if}

	{#if tip}
		<div
			class="bg-foreground text-background pointer-events-none absolute z-50 -translate-y-full rounded-md px-2 py-1 text-xs shadow-md"
			style:left="{Math.min(mouse.x + 10, width - 180)}px"
			style:top="{mouse.y - 10}px"
			style:max-width="240px"
		>
			{#if tip.kind === 'zone'}
				<div class="font-semibold">{zoneClassLabel(tip.zone)}</div>
				<div class="text-background/70 mt-0.5 whitespace-normal">
					{tip.zone.tooltipDefinition()}
				</div>
				<div class="text-background/70 mt-0.5 tabular-nums">
					{m.scatter_tooltip_population({ count: zonePopulation(tip.zone.className) })}
				</div>
			{:else}
				<div class="font-semibold">{tip.sample.name}</div>
				{@const tipT =
					tip.sample.a != null && tip.sample.i != null
						? tisserand(tip.sample.a, tip.sample.e, tip.sample.i)
						: null}
				<div class="text-background/70 tabular-nums">
					a={tip.sample.a == null ? '—' : formatNumber(tip.sample.a)} · e={formatNumber(
						tip.sample.e
					)}
					· q={formatNumber(tip.sample.q)}{#if activePlot === 'a-T' && tipT != null}
						· T<sub>J</sub>={formatNumber(tipT)}{/if}
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
