<script lang="ts">
	/**
	 * The atmosphere seen edge-on: the body's limb curving across the bottom and
	 * its named layers stacked above it, to scale by height up to the mesopause
	 * or whatever plays its part.
	 *
	 * The thermosphere, exosphere and corona are capped to a fixed band each.
	 * Earth's exosphere reaches ~10,000 km against a 12 km troposphere, so drawn
	 * to scale the weather layer is a hairline and everything readable is vacuum.
	 * They hold essentially none of the atmosphere's mass, which is what makes
	 * that honest rather than convenient; their real height stays in the label.
	 *
	 * The limb's centre sits left of the frame so the right half stays clear for
	 * the labels. Each carries the layer's temperature from bottom to top beside
	 * the name, and the height and pressure of its top boundary under it — the
	 * layout the interior cross-section uses, so temperature is in the same place
	 * on both halves of the tab.
	 *
	 * Bottom to top rather than one reading, because the data describes every
	 * layer by its top: Venus's tropopause is 245 K under a 737 K surface, and a
	 * label saying "troposphere 245 K" contradicts everything else on the body.
	 */
	import * as m from '$lib/paraglide/messages.js';
	import type { AtmosphereStructure } from '$lib/fetch/objects/object-data';
	import { atmosphereProfile, type AtmosphereBand } from '$lib/charts/atmosphere-cross-section';
	import { atmosphereLayerName } from '$lib/charts/atmosphere-layers';
	import { spreadRows, stackedRows } from '$lib/charts/label-fit';
	import { formatKm, formatKmRange } from '$lib/format/distance';
	import { formatPressure } from '$lib/format/pressure';
	import {
		formatTemperature,
		formatTemperatureRange,
		formatTemperatureSpan
	} from '$lib/format/temperature';
	import { ltrIsolate } from '$lib/format/bidi';
	import * as Tooltip from '$lib/components/ui/tooltip';

	interface Props {
		structure: AtmosphereStructure;
		/** Hue the bands are drawn in — the dominant gas's, so this chart and the
		 *  composition bar agree on what the air is made of. */
		color?: string;
	}

	let { structure, color = 'rgb(120 160 210)' }: Props = $props();

	let profile = $derived(atmosphereProfile(structure));

	// Matches the drawer's content width, so the label sizes below render at the
	// sizes they say.
	const W = 264;
	const H = 190;
	/** Apex pushed left of centre: the labels need the other half. */
	const CX = 72;
	/** A radius far larger than the frame, so the limb reads as a gentle curve
	 *  rather than as a circle that happens to be cropped. */
	const PLANET_R = 520;
	/** How much of the frame the drawn atmosphere occupies. */
	const AIR = 132;
	const GROUND_Y = H - 18;
	const CY = GROUND_Y + PLANET_R;
	/** Where the labels begin. Far enough left that a long layer name and its
	 *  temperature share one line — the Sun's "Région de transition · 999 700 ℃"
	 *  is the widest pair any body asks for. */
	const GUTTER = 114;
	/** The scrim stays put when the gutter moves: it is placed against the limb
	 *  it has to fade out, not against the text. */
	const SCRIM_X = 92;
	const LABEL_SPACING = 26;

	const DATUM_LABEL: Record<string, () => string> = {
		surface: m.atmosphere_datum_surface,
		one_bar: m.atmosphere_datum_one_bar,
		photosphere: m.atmosphere_datum_photosphere
	};

	function km(value: number): string {
		return ltrIsolate(formatKm(value));
	}

	/** Half-width the arcs have to span to run clear off both edges. */
	const SPAN = Math.max(CX, W - CX) + 24;

	/** Where the circle of radius `r` crosses this horizontal offset from the
	 *  apex. */
	function pointOn(r: number, dx: number): [number, number] {
		return [CX + dx, CY - Math.sqrt(Math.max(r * r - dx * dx, 0))];
	}

	/** The shell between two heights, closed off the sides of the frame. */
	function bandPath(base: number, top: number): string {
		const r0 = PLANET_R + base * AIR;
		const r1 = PLANET_R + top * AIR;
		const [ax, ay] = pointOn(r1, -SPAN);
		const [bx, by] = pointOn(r1, SPAN);
		const [cx2, cy2] = pointOn(r0, SPAN);
		const [dx2, dy2] = pointOn(r0, -SPAN);
		return (
			`M ${ax} ${ay} A ${r1} ${r1} 0 0 1 ${bx} ${by} ` +
			`L ${cx2} ${cy2} A ${r0} ${r0} 0 0 0 ${dx2} ${dy2} Z`
		);
	}

	/** Just the arc at one height, for drawing a boundary as a line. */
	function boundaryPath(height: number): string {
		const r = PLANET_R + height * AIR;
		const [ax, ay] = pointOn(r, -SPAN);
		const [bx, by] = pointOn(r, SPAN);
		return `M ${ax} ${ay} A ${r} ${r} 0 0 1 ${bx} ${by}`;
	}

	/** The body under the air, filled down to the bottom of the frame. */
	function groundPath(): string {
		const [ax, ay] = pointOn(PLANET_R, -SPAN);
		const [bx, by] = pointOn(PLANET_R, SPAN);
		return `M ${ax} ${ay} A ${PLANET_R} ${PLANET_R} 0 0 1 ${bx} ${by} L ${bx} ${H} L ${ax} ${H} Z`;
	}

	function kelvin(value: number): string {
		return ltrIsolate(formatTemperature({ value, unit: 'kelvin' }));
	}

	/**
	 * What the layer runs between, on the name line — the same place the interior
	 * cross-section puts a layer's temperature.
	 *
	 * One end is missing wherever the profile is: Neptune's stratosphere is
	 * unmeasured above its tropopause, and no exosphere ends anywhere. Those read
	 * as open rather than as a layer sitting at one temperature.
	 */
	function temperature(band: AtmosphereBand): string | null {
		const bottom = band.baseTemperatureK;
		const top = band.layer.top_temperature_k;
		if (bottom !== null && top !== undefined) {
			return ltrIsolate(
				formatTemperatureSpan({ value: bottom, unit: 'kelvin' }, { value: top, unit: 'kelvin' })
			);
		}
		if (top !== undefined) return m.structure_temperature_up_to({ value: kelvin(top) });
		if (bottom !== null) return m.structure_temperature_from({ value: kelvin(bottom) });
		return null;
	}

	/** Where the boundary is and what the air is down to there. */
	function readings(layer: { top_km?: number; top_pressure_pa?: number }): string {
		const bits: string[] = [];
		if (layer.top_km !== undefined) bits.push(km(layer.top_km));
		if (layer.top_pressure_pa !== undefined)
			bits.push(ltrIsolate(formatPressure(layer.top_pressure_pa)));
		return bits.join(' · ');
	}

	/**
	 * The hover, which is where each number is said to belong to an end rather
	 * than to the layer. Stacked the way the layer is: its top first, then the
	 * width published around that boundary, then the base it stands on.
	 *
	 * Everything on the top line is the top boundary, including the pressure,
	 * which is a quarter of the surface's on Earth.
	 */
	function tooltip(band: AtmosphereBand): string[] {
		const lines: string[] = [];
		const layer = band.layer;
		const top = [readings(layer)].filter(Boolean);
		if (layer.top_temperature_k !== undefined) top.push(kelvin(layer.top_temperature_k));
		if (top.length) lines.push(m.structure_layer_top({ value: top.join(' · ') }));

		const widths: string[] = [];
		if (layer.top_km_range)
			widths.push(ltrIsolate(formatKmRange(layer.top_km_range[0], layer.top_km_range[1])));
		if (layer.top_temperature_range_k)
			widths.push(
				ltrIsolate(
					formatTemperatureRange(
						{ value: layer.top_temperature_range_k[0], unit: 'kelvin' },
						{ value: layer.top_temperature_range_k[1], unit: 'kelvin' }
					)
				)
			);
		if (widths.length) lines.push(m.structure_boundary_spread({ value: widths.join(' · ') }));

		if (band.baseTemperatureK !== null) {
			lines.push(m.structure_layer_bottom({ value: kelvin(band.baseTemperatureK) }));
		}
		// Last, and only where it applies: the one thing the drawing gets wrong
		// belongs on the band that is drawn wrong, not under the whole chart.
		if (band.capped) lines.push(m.structure_atmosphere_capped());
		return lines;
	}

	interface Row {
		band: AtmosphereBand;
		index: number;
		anchorY: number;
		labelY: number;
	}

	let rows: Row[] = $derived.by(() => {
		if (!profile) return [];
		const entries = profile.bands.map((band, i) => ({
			band,
			index: i,
			anchorY: GROUND_Y - ((band.base + band.top) / 2) * AIR
		}));
		// Top of the stack first, so the spread runs down the frame in the order
		// the labels appear.
		entries.reverse();
		return spreadRows(entries, LABEL_SPACING, 12, H - 10);
	});

	// Where a name and its temperature cannot share the line, the temperature
	// drops to the line below and right-aligns beside the height.
	let nameEls = $state<(SVGTextElement | undefined)[]>([]);
	let readingEls = $state<(SVGTextElement | undefined)[]>([]);
	let stacked = $derived(stackedRows(rows, nameEls, readingEls, W - 2 - (GUTTER + 4)));
</script>

<!-- The leader line and the two text lines, shared so that a row reads the same
     whether or not it has anything to say on hover. -->
{#snippet label(row: Row, i: number)}
	{@const value = temperature(row.band)}
	<path
		d="M {SCRIM_X - 26} {row.anchorY} L {GUTTER - 8} {row.labelY - 3} L {GUTTER} {row.labelY - 3}"
		class="stroke-border fill-none"
		stroke-width="1"
	/>
	<text bind:this={nameEls[i]} x={GUTTER + 4} y={row.labelY} class="fill-foreground text-[10px]">
		{atmosphereLayerName(row.band.layer.role)}
	</text>
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
	<text x={GUTTER + 4} y={row.labelY + 11} class="fill-muted-foreground text-[9px]">
		{readings(row.band.layer)}
	</text>
{/snippet}

{#if profile && profile.bands.length}
	<div class="bg-muted/25 border-border/60 overflow-hidden rounded-md border p-2">
		<svg
			viewBox="0 0 {W} {H}"
			class="w-full"
			role="img"
			aria-label={m.structure_atmosphere_chart()}
		>
			{#each profile.bands as band, i (band.layer.role + i)}
				<path d={bandPath(band.base, band.top)} fill={color} opacity={band.opacity}></path>
			{/each}

			<!-- The labels sit over the limb, so the sky fades out under them
			     rather than the text fighting the band it crosses. -->
			<defs>
				<linearGradient id="atmo-scrim" x1="0" x2="1" y1="0" y2="0">
					<stop offset="0" stop-color="var(--background)" stop-opacity="0" />
					<stop offset="0.55" stop-color="var(--background)" stop-opacity="0.9" />
					<stop offset="1" stop-color="var(--background)" stop-opacity="0.9" />
				</linearGradient>
			</defs>
			<!-- Every boundary gets a line of its own, so a layer too thin to
			     draw is still visible as the line at its top. Uranus's 50 km
			     troposphere under a 4,000 km stratosphere is 1% of the chart, and
			     to scale that is a band a pixel high. -->
			{#each profile.bands as band, i (band.layer.role + i)}
				<path
					d={boundaryPath(band.top)}
					fill="none"
					stroke="rgb(255 255 255 / 0.35)"
					stroke-dasharray={band.capped ? '3 3' : undefined}
					stroke-width="0.75"
				/>
			{/each}

			<!-- The body itself, so the air reads as sitting on something. -->
			<path
				d={groundPath()}
				fill="rgb(58 58 62)"
				stroke="rgb(255 255 255 / 0.25)"
				stroke-width="0.75"
			/>
			<text x="8" y={GROUND_Y + 13} class="fill-white/70 text-[9px]">
				{(DATUM_LABEL[structure.datum] ?? DATUM_LABEL.surface)()}
			</text>

			<rect x={SCRIM_X} y="0" width={W - SCRIM_X} height={H} fill="url(#atmo-scrim)" />

			{#each rows as row, i (row.index)}
				{@const lines = tooltip(row.band)}
				{#if lines.length}
					<Tooltip.Root>
						<Tooltip.Trigger>
							{#snippet child({ props })}
								<g class="cursor-help" {...props}>{@render label(row, i)}</g>
							{/snippet}
						</Tooltip.Trigger>
						<Tooltip.Content class="flex-col items-start gap-0">
							{#each lines as line (line)}<span>{line}</span>{/each}
						</Tooltip.Content>
					</Tooltip.Root>
				{:else}
					<g>{@render label(row, i)}</g>
				{/if}
			{/each}
		</svg>
	</div>
{/if}
