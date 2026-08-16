<script lang="ts">
	/**
	 * The body cut open: a quarter disc of nested shells, to scale by radius.
	 * The quarter opens away from its vertical edge, so that edge doubles as
	 * the radius axis and the line labels stand beside.
	 *
	 * Shells are coloured to look right, not to tell apart — see
	 * `layer-appearance.ts`. The composition bars below use the categorical
	 * palette instead, since telling materials apart is their whole job.
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
	import type { AtmosphereStructure } from '$lib/fetch/objects/object-data';
	import {
		FRAME_W as W,
		FRAME_H as H,
		LABEL_MAX_Y,
		SECOND_LINE_DY,
		remeasure,
		spreadRows,
		stackedRows
	} from '$lib/charts/label-fit';
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
		/** What the body's radius is measured to, which is what the outer end of
		 *  the axis is. A giant has no surface to name and the Sun quotes its
		 *  photosphere. */
		datum?: AtmosphereStructure['datum'];
		active?: number | null;
	}

	let {
		section,
		atmosphereColor = 'rgb(150 165 185)',
		temperatures = [],
		plasmaRange,
		datum = 'surface',
		active = $bindable(null)
	}: Props = $props();

	const DATUM_LABEL: Record<string, () => string> = {
		surface: m.structure_disc_surface,
		one_bar: m.structure_disc_one_bar,
		photosphere: m.structure_disc_photosphere
	};

	/** Centre of the body, at the foot of the vertical edge the quarter opens
	 *  away from. */
	// Trades a tenth of its radius for the label gutter: a name and its
	// temperature need to fit one line, even "Noyau externe · 5 127–5 727 ℃".
	const CX = 118;
	const CY = H - 22;
	const R = 114;
	/** Where the labels begin, just clear of that edge. */
	const GUTTER = CX + 9;
	const LABEL_SPACING = 25;

	// The body shrinks to leave room for the atmosphere strip outside it,
	// rather than overflow the frame — Titan's is 19% of its radius, Earth's
	// a 1.3% hairline, and drawing it thicker would break the to-scale claim.
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

	/** Each band anchors its label at its own midpoint on the radius axis —
	 *  core near the bottom, crust near the top — then slides apart only where
	 *  two would overlap. */
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
		return spreadRows(entries, LABEL_SPACING, 14, LABEL_MAX_Y);
	});

	// Where a name and its temperature cannot share the line, the temperature
	// drops to the line below and right-aligns beside the depth range.
	let nameEls = $state<(SVGTextElement | undefined)[]>([]);
	let readingEls = $state<(SVGTextElement | undefined)[]>([]);
	let stacked = $state<boolean[]>([]);
	let svgEl = $state<SVGSVGElement>();

	// An effect, not a derived, so the text exists in the DOM before it's
	// measured (see `stackedRows`). Runs even while hidden, but only applies
	// where the chart actually has a box to measure.
	$effect(() =>
		remeasure(svgEl, () => {
			const next = stackedRows(rows, nameEls, readingEls, W - 2 - GUTTER);
			if (svgEl?.getClientRects().length) stacked = next;
		})
	);
</script>

<div class="bg-muted/25 border-border/60 rounded-md border p-2">
	<!-- What the drawing is worth, above it rather than in it: every corner of
	     the frame belongs to a label that moves with the body's own layers, and
	     the only one free on Earth is taken on the Sun. -->
	<div class="text-muted-foreground mb-1 text-end text-[10px] tabular-nums">
		{m.structure_to_scale_radius({ value: ltrIsolate(formatKm(section.radiusKm)) })}
	</div>
	<svg
		bind:this={svgEl}
		viewBox="0 0 {W} {H}"
		class="w-full"
		role="img"
		aria-label={m.structure_interior_chart({ count: section.bands.length })}
	>
		<defs>
			<!-- Diffuse layers fade rather than cut sharply, since they have no
			     real boundary — only where something else sits above to fade
			     into (not on an outermost diffuse layer, e.g. Uranus). The
			     gradient spans the outer half; anchoring it to a fixed radius
			     fraction instead left thick layers solid-coloured everywhere. -->
			{#each section.bands as band, i (band.layer.role + i)}
				{#if band.layer.diffuse && i > 0}
					<radialGradient id="diffuse-{i}" gradientUnits="userSpaceOnUse" cx={CX} cy={CY} r={bodyR}>
						<stop offset={(band.inner + band.outer) / 2} stop-color={fill(band, i)} />
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
				<!-- A band under a diffuse one runs to the centre — stopping at its
				     nominal boundary would let the fade dissolve into the card,
				     drawing exactly the crisp edge the gradient exists to avoid. -->
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

		<!-- Outer end is labelled by what the radius is measured to, not
		     "surface" — Jupiter has none, and the atmosphere chart above
		     measures its own heights from the 1 bar level. -->
		<text x={CX - 3} y={CY - R - 6} text-anchor="end" class="fill-muted-foreground text-[9px]">
			{(DATUM_LABEL[datum] ?? DATUM_LABEL.surface)()}
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
							y={row.labelY + (stacked[i] ? SECOND_LINE_DY : 0)}
							text-anchor="end"
							class="fill-muted-foreground text-[9px]"
						>
							{value}
						</text>
					{/if}
				{/if}
				<text x={GUTTER} y={row.labelY + SECOND_LINE_DY} class="fill-muted-foreground text-[9px]">
					{row.band ? depthRange(row.band) : ltrIsolate(formatKm(section.atmosphere?.km ?? 0))}
				</text>
			</g>
		{/each}
	</svg>
</div>
