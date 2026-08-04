<script lang="ts">
	/**
	 * The body cut open: a quarter disc of nested shells, to scale by radius.
	 *
	 * The quarter opens away from its vertical edge, so that edge is both the
	 * axis radius is measured along and the one the labels stand beside — each
	 * shell's name ends up level with the shell rather than pointing at it from
	 * across the disc.
	 *
	 * Shells are drawn the colour they would look rather than the colour that
	 * tells them apart — see `layer-appearance.ts`. The composition bars under
	 * the chart keep the categorical palette, where telling nine materials apart
	 * is the whole job.
	 */
	import * as m from '$lib/paraglide/messages.js';
	import {
		bandPath,
		type InteriorBand,
		type InteriorCrossSection
	} from '$lib/charts/interior-cross-section';
	import {
		bandColor,
		type PlasmaRange,
		type TemperatureBracket
	} from '$lib/charts/layer-appearance';
	import { layerName } from '$lib/charts/interior-layers';
	import { FRAME_W as W, FRAME_H as H, spreadRows, stackedRows } from '$lib/charts/label-fit';
	import { formatKm, formatKmRange } from '$lib/format/distance';
	import { formatKelvinRange } from '$lib/format/temperature';
	import { ltrIsolate } from '$lib/format/bidi';

	interface Props {
		section: InteriorCrossSection;
		/** What the strip is filled with — the sky's colour off the composition,
		 *  so the strip and the atmosphere chart describe the same air. */
		atmosphereColor?: string;
		/** Per layer index, for the ones the body has a reading for — a bracket
		 *  where the value is modelled rather than measured. Everything else stays
		 *  at its material's colour and says nothing. */
		temperatures?: (TemperatureBracket | null)[];
		/** Anchors for shading a star's zones, which sit between two readings and
		 *  have none of their own. */
		plasmaRange?: PlasmaRange;
		active?: number | null;
	}

	let {
		section,
		atmosphereColor = 'rgb(150 165 185)',
		temperatures = [],
		plasmaRange,
		active = $bindable(null)
	}: Props = $props();

	/** The centre of the body, at the foot of the vertical edge. The quarter
	 *  opens up and to the *left* of it, so the edge the labels stand beside is
	 *  the one radius is measured along. */
	// The disc gives up a tenth of its radius to the labels beside it: a layer
	// name and its temperature have to sit on one line in every locale, and
	// "Noyau externe · 5 127–5 727 ℃" does not fit beside a disc any wider.
	const CX = 118;
	const CY = H - 22;
	const R = 114;
	/** Where the labels begin, just clear of that edge. */
	const GUTTER = CX + 9;
	const LABEL_SPACING = 25;

	// The atmosphere strip rides outside the body, so the body shrinks to leave
	// room for it rather than overflowing the frame. Titan's is 19% of its
	// radius; Earth's is 1.3%, a hairline, and drawing it thicker would be a lie
	// on a chart whose whole claim is that it is to scale.
	let bodyR = $derived(R / (1 + (section.atmosphere?.height ?? 0)));

	function fill(band: InteriorBand, i: number): string {
		return bandColor(band, temperatures[i], plasmaRange);
	}

	/** Rides on the name line, the way the atmosphere chart's boundary readings
	 *  do — the two cross-sections put temperature in the same place. */
	function reading(i: number): string | null {
		const value = temperatures[i];
		return value ? formatKelvinRange(value.lowK, value.highK) : null;
	}

	/** "0–50 km", the way anyone places a layer. */
	function depthRange(band: InteriorBand): string {
		return ltrIsolate(formatKmRange(band.depthFromKm, band.depthToKm));
	}

	/**
	 * A band's own slice of the vertical edge, which is where its label goes.
	 *
	 * The disc opens away from that edge, so radius measured straight up it is
	 * the same axis the labels are stacked on: the core's label sits by the core
	 * at the bottom, the crust's by the crust at the top. Anchored at each
	 * band's midpoint, then slid apart only where two would overlap.
	 */
	let rows = $derived.by(() => {
		const entries: { band: InteriorBand | null; index: number; anchorY: number }[] =
			section.bands.map((band, i) => ({
				band,
				index: i,
				anchorY: CY - ((band.outer + band.inner) / 2) * bodyR
			}));
		if (section.atmosphere) {
			entries.unshift({ band: null, index: -1, anchorY: CY - (bodyR + R) / 2 });
		}
		// Outermost first, which is already top-to-bottom down the edge — the
		// order `spreadRows` expects.
		return spreadRows(entries, LABEL_SPACING, 14, H - 10);
	});

	// Where a name and its temperature cannot share the line, the temperature
	// drops to the line below and right-aligns beside the depth range.
	let nameEls = $state<(SVGTextElement | undefined)[]>([]);
	let readingEls = $state<(SVGTextElement | undefined)[]>([]);
	let stacked = $derived(stackedRows(rows, nameEls, readingEls, W - 2 - GUTTER));
</script>

<div class="bg-muted/25 border-border/60 rounded-md border p-2">
	<svg
		viewBox="0 0 {W} {H}"
		class="w-full"
		role="img"
		aria-label={m.structure_interior_chart({ count: section.bands.length })}
	>
		<defs>
			<!-- A diffuse layer has no surface: Jupiter's core is heavy elements
			     smeared through the envelope, and a crisp edge would draw a
			     boundary the paper says is not there. It only fades where there
			     is something above to fade *into* — on Uranus the whole planet is
			     one diffuse layer, and fading it out at the surface would draw a
			     body evaporating into the page. -->
			{#each section.bands as band, i (band.layer.role + i)}
				{#if band.layer.diffuse && i > 0}
					<radialGradient id="diffuse-{i}" gradientUnits="userSpaceOnUse" cx={CX} cy={CY} r={bodyR}>
						<stop offset={band.outer * 0.3} stop-color={fill(band, i)} />
						<stop offset={band.outer} stop-color={fill(band, i)} stop-opacity="0" />
					</radialGradient>
				{/if}
			{/each}
		</defs>

		<!-- Mirrored about the vertical edge, so the quarter opens away from the
		     labels instead of across them. -->
		<g transform="matrix(-1,0,0,1,{2 * CX},0)">
			{#if section.atmosphere}
				<!-- A minimum of a pixel and a half: on Earth this is 1.7px to scale,
				     and rounding it away would drop the layer entirely. -->
				{@const outer = Math.max(R, bodyR + 1.5)}
				<path
					d={bandPath({ outer: outer / bodyR, inner: 1 }, CX, CY, bodyR)}
					fill={atmosphereColor}
					opacity="0.8"
				/>
			{/if}

			{#each section.bands as band, i (band.layer.role + i)}
				<!-- A band sitting on a diffuse one runs all the way to the centre:
				     the diffuse layer fades into it from above, and stopping it at
				     the nominal boundary would leave the fade dissolving into the
				     card and draw the edge the gradient exists to avoid. -->
				{@const over = section.bands[i + 1]?.layer.diffuse === true}
				{@const fades = band.layer.diffuse && i > 0}
				<path
					d={bandPath(over ? { ...band, inner: 0 } : band, CX, CY, bodyR)}
					fill={fades ? `url(#diffuse-${i})` : fill(band, i)}
					class="transition-opacity"
					opacity={active === null || active === i ? 1 : 0.4}
					stroke={fades ? 'none' : 'rgb(0 0 0 / 0.45)'}
					stroke-width="0.8"
					role="presentation"
					onmouseenter={() => (active = i)}
					onmouseleave={() => (active = null)}
				/>
			{/each}
		</g>

		<!-- Which end of the edge is which. Both sit clear of the disc, above
		     its apex and below its centre. -->
		<text x={CX - 3} y={CY - R - 6} text-anchor="end" class="fill-muted-foreground text-[9px]">
			{m.structure_disc_surface()}
		</text>
		<text x={CX - 3} y={CY + 11} text-anchor="end" class="fill-muted-foreground text-[9px]">
			{m.structure_disc_centre()}
		</text>

		{#each rows as row, i (row.index)}
			<g
				class="transition-opacity"
				opacity={active === null || active === row.index ? 1 : 0.4}
				role="presentation"
				onmouseenter={() => (active = row.index)}
				onmouseleave={() => (active = null)}
			>
				<!-- Usually a stub a few pixels long: the label is already beside
				     the band. It only stretches where two labels had to be pushed
				     apart to stop them overlapping. -->
				<path
					d="M {CX} {row.anchorY} L {GUTTER - 3} {row.labelY - 3}"
					class="stroke-border fill-none"
					stroke-width="1"
				/>
				<text bind:this={nameEls[i]} x={GUTTER} y={row.labelY} class="fill-foreground text-[10px]">
					{row.band
						? layerName(row.band.layer.role, row.band.layer.note)
						: m.structure_layer_atmosphere()}
				</text>
				{#if row.band}
					{@const value = reading(row.index)}
					{#if value}
						<text
							bind:this={readingEls[i]}
							x={W - 2}
							y={row.labelY + (stacked[i] ? 11 : 0)}
							text-anchor="end"
							class="fill-muted-foreground text-[9px]"
						>
							{value}
						</text>
					{/if}
				{/if}
				<text x={GUTTER} y={row.labelY + 11} class="fill-muted-foreground text-[9px]">
					{row.band ? depthRange(row.band) : ltrIsolate(formatKm(section.atmosphere?.km ?? 0))}
				</text>
			</g>
		{/each}
	</svg>
</div>
