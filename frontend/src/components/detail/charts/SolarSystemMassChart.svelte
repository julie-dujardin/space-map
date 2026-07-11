<script lang="ts">
	import { getContext } from 'svelte';
	import * as Tooltip from '$lib/components/ui/tooltip/index.js';
	import {
		MASS_RESERVOIRS,
		SUN_MASS_EARTHS,
		SUN_COLOR,
		EARTH_MASS_KG
	} from '$lib/data/solar-system-mass';
	import type { AppState } from '$lib/state/app-state.svelte';
	import { applyGroup, serializeUrl } from '$lib/state/url';
	import { isModifiedClick } from '$lib/state/focus-link';
	import { formatNumber } from '$lib/format/quantities';
	import { formatMass, formatMassRange } from '$lib/format/mass';
	import * as m from '$lib/paraglide/messages.js';

	const appState = getContext<AppState | undefined>('appState');

	const nonSolarTotal = MASS_RESERVOIRS.reduce((s, r) => s + r.central, 0);

	// ---- Linear bar: two segments, the Sun (~99.86%) vs everything else ----
	interface Seg {
		key: string;
		label: string;
		mass: number;
		color: string;
		x: number;
		w: number;
		share: number;
	}

	const REST_COLOR = '#8a8f98'; // "everything else" remainder
	const barTotal = SUN_MASS_EARTHS + nonSolarTotal;

	const HEIGHT = 40;
	const BAR_Y = 6;
	const BAR_H = 28;
	const GAP = 1;
	const LABEL_MIN_W = 46; // min segment width to fit an inline name
	let barWidth = $state(0);

	let segments = $derived.by<Seg[]>(() => {
		if (!barWidth) return [];
		const items = [
			{ key: 'sun', label: m.mass_reservoir_sun(), mass: SUN_MASS_EARTHS, color: SUN_COLOR },
			{ key: 'rest', label: m.mass_distribution_rest(), mass: nonSolarTotal, color: REST_COLOR }
		];
		let acc = 0;
		const out: Seg[] = [];
		for (const it of items) {
			const share = it.mass / barTotal;
			const w = share * barWidth;
			out.push({ ...it, x: acc, w, share });
			acc += w;
		}
		return out;
	});

	let hoveredKey = $state<string | null>(null);
	let hovered = $derived(segments.find((s) => s.key === hoveredKey) ?? null);

	let tipWidth = $state(0);
	let tipLeft = $derived.by(() => {
		if (!hovered) return 0;
		const half = tipWidth / 2;
		return Math.min(Math.max(hovered.x + hovered.w / 2, half), Math.max(half, barWidth - half));
	});

	// ---- Log chart: the sub-stellar budget with confidence intervals ----
	const LOG_MIN = -6; // 1e-6 M⊕, just below the smallest reservoir
	const LOG_MAX = 3; //  1e3 M⊕, leaving headroom past the giants
	const LOG_SPAN = LOG_MAX - LOG_MIN;
	function pct(v: number): number {
		const p = ((Math.log10(v) - LOG_MIN) / LOG_SPAN) * 100;
		return Math.min(100, Math.max(0, p));
	}

	// Show the whisker only where the interval is wide enough to read (~5×); the
	// tight Gaussian ones would be a sub-pixel nub.
	const MIN_INTERVAL_RATIO = 5;

	function zoneHref(slug: string, label: string): string | undefined {
		return appState ? serializeUrl(applyGroup(appState.view, slug, label)) : undefined;
	}
	function openZone(slug: string, label: string) {
		return (e: MouseEvent) => {
			if (isModifiedClick(e) || !appState) return;
			e.preventDefault();
			appState.setGroup(slug, label);
		};
	}

	function sharePct(s: number): string {
		const p = s * 100;
		return p >= 0.01 ? `${formatNumber(p)}%` : `${p.toExponential(1)}%`;
	}
</script>

<div class="flex flex-col gap-4">
	<!-- Linear bar -->
	<div class="flex flex-col gap-1">
		<h3 class="text-sm font-medium">{m.mass_distribution_title()}</h3>
		<div class="border-border/60 border-t"></div>
		<div
			class="relative mt-1 w-full"
			bind:clientWidth={barWidth}
			style:height="{HEIGHT}px"
			role="img"
			onmouseleave={() => (hoveredKey = null)}
		>
			{#if barWidth > 0 && segments.length > 0}
				<svg width="100%" height={HEIGHT} viewBox="0 0 {barWidth} {HEIGHT}" class="block">
					<clipPath id="ss-mass-clip">
						<rect x={0} y={BAR_Y} width={barWidth} height={BAR_H} rx="4" />
					</clipPath>
					<g clip-path="url(#ss-mass-clip)">
						{#each segments as s (s.key)}
							{@const active = s.key === hoveredKey}
							<rect
								x={s.x}
								y={BAR_Y}
								width={Math.max(0, s.w - GAP)}
								height={BAR_H}
								fill={s.color}
								opacity={hoveredKey && !active ? 0.55 : 1}
							/>
							{#if s.w >= LABEL_MIN_W}
								<text
									x={s.x + s.w / 2}
									y={BAR_Y + BAR_H / 2}
									text-anchor="middle"
									dominant-baseline="central"
									class="seg-label"
								>
									{s.label}
								</text>
							{/if}
						{/each}
					</g>

					<!-- Hit targets: a min-width band per segment so the remainder stays reachable. -->
					{#each segments as s (s.key)}
						<rect
							x={s.x + s.w / 2 - Math.max(s.w, 6) / 2}
							y={BAR_Y}
							width={Math.max(s.w, 6)}
							height={BAR_H}
							fill="transparent"
							class="cursor-default"
							role="img"
							aria-label="{s.label}: {sharePct(s.share)}"
							onmouseenter={() => (hoveredKey = s.key)}
						/>
					{/each}
				</svg>

				{#if hovered}
					<div
						bind:clientWidth={tipWidth}
						class="bg-popover text-popover-foreground border-border pointer-events-none absolute z-10 -translate-x-1/2 rounded-md border px-2 py-1 text-center whitespace-nowrap shadow-md"
						style:left="{tipLeft}px"
						style:top="{BAR_Y + BAR_H + 6}px"
						style:visibility={tipWidth === 0 ? 'hidden' : 'visible'}
					>
						<div class="text-xs font-medium">{hovered.label}</div>
						<div class="text-muted-foreground text-[11px] tabular-nums">
							{formatMass(hovered.mass * EARTH_MASS_KG)} · {sharePct(hovered.share)}
						</div>
					</div>
				{/if}
			{/if}
		</div>
	</div>

	<!-- Log chart -->
	<div class="flex flex-col gap-1">
		<h3 class="text-sm font-medium">{m.mass_budget_title()}</h3>
		<div class="border-border/60 border-t"></div>
		<div class="mt-1 flex flex-col gap-[3px]">
			{#each MASS_RESERVOIRS as r (r.key)}
				{@const lo = pct(r.lo)}
				{@const hi = pct(r.hi)}
				<Tooltip.Root>
					<Tooltip.Trigger>
						{#snippet child({ props })}
							<a
								{...props}
								href={zoneHref(r.zone, r.label())}
								onclick={openZone(r.zone, r.label())}
								class="hover:bg-muted/40 grid items-center gap-2 rounded-sm px-1 py-px"
								style="grid-template-columns: minmax(0, 9rem) 1fr 4.5rem"
							>
								<div class="text-muted-foreground truncate text-sm" title={r.label()}>
									{r.label()}
								</div>
								<div class="bg-muted/30 relative h-[16px] rounded-sm">
									<div
										class="absolute top-1/2 start-0 h-[10px] -translate-y-1/2 rounded-sm"
										style="width: {pct(r.central)}%; background: {r.color}"
									></div>
									<!-- 16th–84th percentile whisker -->
									{#if r.hi / r.lo >= MIN_INTERVAL_RATIO}
										<div
											class="absolute top-1/2 -translate-y-1/2"
											style="inset-inline-start: {lo}%; width: {hi - lo}%; height: 8px"
										>
											<div
												class="bg-foreground/55 absolute top-1/2 start-0 h-px w-full -translate-y-1/2"
											></div>
											<div class="bg-foreground/55 absolute top-0 start-0 h-full w-px"></div>
											<div class="bg-foreground/55 absolute top-0 end-0 h-full w-px"></div>
										</div>
									{/if}
								</div>
								<div class="text-muted-foreground text-end text-sm tabular-nums">
									{sharePct(r.central / nonSolarTotal)}
								</div>
							</a>
						{/snippet}
					</Tooltip.Trigger>
					<Tooltip.Content class="flex-col items-start gap-0.5">
						<div class="font-medium">{r.label()}</div>
						<div class="tabular-nums">{formatMass(r.central * EARTH_MASS_KG)}</div>
						{#if r.hi / r.lo >= MIN_INTERVAL_RATIO}
							<div class="text-background/70 tabular-nums">
								{formatMassRange(r.lo * EARTH_MASS_KG, r.hi * EARTH_MASS_KG)}
							</div>
							<div class="text-background/55 text-[11px]">{m.mass_budget_percentile()}</div>
						{/if}
					</Tooltip.Content>
				</Tooltip.Root>
			{/each}
		</div>
		<p class="text-muted-foreground mt-1 text-[10px] leading-snug">
			{m.mass_budget_note()}
			<a
				href="https://arxiv.org/abs/2603.17561"
				target="_blank"
				rel="noopener noreferrer"
				class="underline">{m.mass_budget_source()}</a
			>
		</p>
	</div>
</div>

<style>
	.seg-label {
		font-size: 11px;
		font-weight: 500;
		fill: var(--color-foreground);
		paint-order: stroke;
		stroke: var(--color-background);
		stroke-width: 3px;
		stroke-linejoin: round;
	}
</style>
