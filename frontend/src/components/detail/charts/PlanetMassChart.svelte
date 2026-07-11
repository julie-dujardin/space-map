<script lang="ts">
	import type { NotableMemberEntry } from '$lib/fetch/groups/details';
	import { getContext } from 'svelte';
	import { BODY_COLORS, DEFAULT_BODY_COLOR } from '$lib/constants';
	import type { AppState } from '$lib/state/app-state.svelte';
	import type { FocusObject } from '$lib/state/focusable';
	import { focusClick, focusHref } from '$lib/state/focus-link';
	import { formatNumber, formatQuantity } from '$lib/format/quantities';
	import * as m from '$lib/paraglide/messages.js';

	interface Props {
		members: NotableMemberEntry[];
		localizedNames?: Record<string, string>;
	}
	let { members, localizedNames }: Props = $props();

	const appState = getContext<AppState | undefined>('appState');
	const focusObject = getContext<FocusObject | undefined>('focusObject');

	// One Earth mass (kg) — the unit the chart expresses masses in.
	const EARTH_MASS_KG = 5.97237e24;

	interface Planet {
		id: string;
		name: string;
		massEarths: number;
		share: number; // fraction of the 8-planet total
	}

	// Each planet's segment width is its share of the 8-planet total, so the area
	// encodes the mass repartition — the giants (Jupiter ~71%, Saturn ~21%)
	// dominate. Mass is the export-supplied `mass_kg` (PCK GM, the same source the
	// 3D scene uses); the members on this page are exactly the eight planets.
	// Heaviest → lightest, so the dominant giants lead and the slivers trail.
	let planets = $derived.by<Planet[]>(() => {
		const raw = members
			.filter((mm) => mm.id && mm.mass_kg != null)
			.map((mm) => ({
				id: mm.id as string,
				name: localizedNames?.[mm.id as string] ?? mm.name,
				massEarths: (mm.mass_kg as number) / EARTH_MASS_KG
			}));
		const total = raw.reduce((s, p) => s + p.massEarths, 0) || 1;
		return raw
			.map((p) => ({ ...p, share: p.massEarths / total }))
			.sort((a, b) => b.massEarths - a.massEarths);
	});

	const HEIGHT = 52;
	const BAR_Y = 8;
	const BAR_H = 30;
	// Inline name shown only where the segment is wide enough to hold it.
	const LABEL_MIN_W = 46;
	const GAP = 1; // px separator carved out of each segment's right edge
	let width = $state(0);

	type Seg = Planet & { x: number; w: number };
	let segments = $derived.by<Seg[]>(() => {
		if (!width) return [];
		let acc = 0;
		const out: Seg[] = [];
		for (const p of planets) {
			const w = p.share * width;
			out.push({ ...p, x: acc, w });
			acc += w;
		}
		return out;
	});

	let hoveredId = $state<string | null>(null);
	let hovered = $derived(segments.find((s) => s.id === hoveredId) ?? null);

	// Clamp the tooltip's center by its own half-width so the whole box stays
	// inside the graph (nowrap means clamping the center alone isn't enough).
	let tipWidth = $state(0);
	let tipLeft = $derived.by(() => {
		if (!hovered) return 0;
		const half = tipWidth / 2;
		return Math.min(Math.max(hovered.x + hovered.w / 2, half), Math.max(half, width - half));
	});

	function sharePct(s: number): string {
		return `${formatNumber(s * 100)}%`;
	}
</script>

<div class="flex flex-col gap-1">
	<h3 class="text-sm font-medium">{m.mass_distribution_title()}</h3>
	<div class="border-border/60 border-t"></div>
	<div
		class="relative mt-1 w-full"
		bind:clientWidth={width}
		style:height="{HEIGHT}px"
		role="group"
		aria-label={m.mass_distribution_title()}
		onmouseleave={() => (hoveredId = null)}
	>
		{#if width > 0 && segments.length > 0}
			<svg width="100%" height={HEIGHT} viewBox="0 0 {width} {HEIGHT}" class="block">
				<clipPath id="mass-bar-clip">
					<rect x={0} y={BAR_Y} {width} height={BAR_H} rx="4" />
				</clipPath>
				<g clip-path="url(#mass-bar-clip)">
					{#each segments as s (s.id)}
						{@const color = BODY_COLORS[s.id] ?? DEFAULT_BODY_COLOR}
						{@const active = s.id === hoveredId}
						<rect
							x={s.x}
							y={BAR_Y}
							width={Math.max(0, s.w - GAP)}
							height={BAR_H}
							fill={color}
							opacity={hoveredId && !active ? 0.55 : 1}
						/>
						{#if s.w >= LABEL_MIN_W}
							<text
								x={s.x + s.w / 2}
								y={BAR_Y + BAR_H / 2}
								text-anchor="middle"
								dominant-baseline="central"
								class="seg-label"
							>
								{s.name}
							</text>
						{/if}
					{/each}
				</g>

				<!-- hit targets: a min-width band per planet so the slivers stay reachable -->
				{#each segments as s (s.id)}
					<a
						href={focusHref(appState, s.id, s.name)}
						onclick={focusClick(focusObject, s.id, s.name)}
						onmouseenter={() => (hoveredId = s.id)}
						onfocus={() => (hoveredId = s.id)}
						onblur={() => hoveredId === s.id && (hoveredId = null)}
						aria-label="{s.name}: {sharePct(s.share)}"
					>
						<rect
							x={s.x + s.w / 2 - Math.max(s.w, 6) / 2}
							y={BAR_Y}
							width={Math.max(s.w, 6)}
							height={BAR_H}
							fill="transparent"
							class="cursor-pointer"
						/>
					</a>
				{/each}
			</svg>

			{#if hovered}
				<div
					bind:clientWidth={tipWidth}
					class="bg-foreground text-background pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-full rounded-md px-2 py-1 text-center whitespace-nowrap shadow-md"
					style:left="{tipLeft}px"
					style:top="{BAR_Y - 6}px"
					style:visibility={tipWidth === 0 ? 'hidden' : 'visible'}
				>
					<div class="text-xs font-medium">{hovered.name}</div>
					<div class="text-background/70 text-[11px] tabular-nums">
						{formatQuantity({ value: hovered.massEarths, unit: 'earth_mass' })} · {sharePct(
							hovered.share
						)}
					</div>
				</div>
			{/if}
		{/if}
	</div>
</div>

<style>
	.seg-label {
		font-size: 10px;
		font-weight: 500;
		fill: var(--color-foreground);
		paint-order: stroke;
		stroke: var(--color-background);
		stroke-width: 3px;
		stroke-linejoin: round;
	}
</style>
