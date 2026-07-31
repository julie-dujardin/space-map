<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import * as Tooltip from '$lib/components/ui/tooltip/index.js';
	import type {
		TemperaturePart,
		TemperatureReading,
		Temperatures
	} from '$lib/fetch/objects/object-data';
	import { ucfirst } from '$lib/format/quantities';
	import { formatTemperature } from '$lib/format/temperature';
	import { gradientStops, regimeFor, scalePosition } from '$lib/math/temperature-scale';

	interface Props {
		temperatures: Temperatures;
	}

	let { temperatures }: Props = $props();

	const PART_TITLE: Record<TemperaturePart, () => string> = {
		surface: m.temperature_of_surface,
		cloud_top: m.temperature_of_cloud_top,
		photosphere: m.temperature_of_photosphere,
		corona: m.temperature_of_corona,
		core: m.temperature_of_core
	};
	const PART_LABEL: Record<TemperaturePart, () => string> = {
		surface: m.temperature_part_surface,
		cloud_top: m.temperature_part_cloud_top,
		photosphere: m.temperature_part_photosphere,
		corona: m.temperature_part_corona,
		core: m.temperature_part_core
	};
	const READING_LABEL = {
		min: m.temperature_reading_min,
		mean: m.temperature_reading_mean,
		max: m.temperature_reading_max
	} as const;

	// One bar for the whole body: a reading is only legible next to the others.
	let entries = $derived(temperatures.readings);
	let parts = $derived(new Set(entries.map((r) => r.part)));
	let regime = $derived(regimeFor(entries.map((r) => r.k)));

	// A condition beats the bare min/max wording wherever the exporter set one:
	// Mercury's extremes are its night and day sides, Earth's are one-off
	// weather records, and "min"/"max" flattens both into the same claim.
	// Otherwise name the part when there are several, else the reading.
	function labelFor(reading: TemperatureReading): string {
		if (reading.condition === 'night') return m.temperature_condition_night();
		if (reading.condition === 'day') return m.temperature_condition_day();
		if (reading.condition === 'record') {
			return reading.kind === 'min'
				? m.temperature_condition_record_low()
				: m.temperature_condition_record_high();
		}
		return parts.size > 1 ? PART_LABEL[reading.part]() : READING_LABEL[reading.kind]();
	}

	let readings = $derived(
		entries
			.map((r) => ({
				kind: r.kind,
				label: labelFor(r),
				kelvin: r.k,
				// Every reading formats the same way whatever the regime — the scale
				// switching to logarithmic is not a reason to switch units under the
				// reader, who would be comparing °C here against K one body away.
				text: formatTemperature({ value: r.k, unit: 'kelvin' })
			}))
			.sort((a, b) => a.kelvin - b.kelvin)
	);

	let estimated = $derived(temperatures.origin === 'estimated');

	let gradient = $derived(
		`linear-gradient(to right, ${gradientStops(regime)
			.map((s) => `${s.color} ${(s.at * 100).toFixed(2)}%`)
			.join(', ')})`
	);
	let pos = $derived((kelvin: number) => scalePosition(kelvin, regime) * 100);

	// Labels sit under their own tick, not in fixed columns — pinned to the bar
	// ends they read as the axis bounds rather than as this body's values.
	// Width is estimated from the character count (tabular digits, text-xs)
	// rather than measured: it only has to be close enough to space them.
	let barWidth = $state(0);
	const CHAR_PX = 6.4;
	const GAP_PX = 10;
	const MIN_SPAN_PX = 12;

	// Most bodies occupy a sliver of a scale that has to reach 1000 K — Uranus
	// spans 49–57 K, under a percent of the bar — so the lit window gets a
	// legible floor, widened around the true centre. Ticks stay where they are.
	let span = $derived.by(() => {
		if (readings.length < 2) return null;
		const start = pos(readings[0].kelvin);
		const end = pos(readings[readings.length - 1].kelvin);
		const floor = barWidth ? (MIN_SPAN_PX / barWidth) * 100 : 0;
		if (end - start >= floor) return { start, end };
		const centre = Math.min(100 - floor / 2, Math.max(floor / 2, (start + end) / 2));
		return { start: centre - floor / 2, end: centre + floor / 2 };
	});

	let placed = $derived.by(() => {
		const centres = readings.map((r) => pos(r.kelvin));
		if (!barWidth) return centres;
		const half = readings.map(
			(r) => ((Math.max(r.label.length, r.text.length) * CHAR_PX + GAP_PX) / 2 / barWidth) * 100
		);
		// Push right off each predecessor, pull back inside the right edge, then
		// re-settle leftwards — three passes converge for a sorted set.
		for (let i = 1; i < centres.length; i++) {
			centres[i] = Math.max(centres[i], centres[i - 1] + half[i - 1] + half[i]);
		}
		for (let i = centres.length - 1; i >= 0; i--) {
			const limit =
				i === centres.length - 1 ? 100 - half[i] : centres[i + 1] - half[i + 1] - half[i];
			centres[i] = Math.min(centres[i], limit);
		}
		for (let i = 0; i < centres.length; i++) {
			const limit = i === 0 ? half[i] : centres[i - 1] + half[i - 1] + half[i];
			centres[i] = Math.max(centres[i], limit);
		}
		return centres;
	});
</script>

<div class="flex flex-col gap-1.5">
	<div class="flex items-baseline gap-2">
		<Tooltip.Root>
			<Tooltip.Trigger>
				{#snippet child({ props })}
					<span
						class="text-muted-foreground w-fit cursor-help text-sm decoration-dotted underline underline-offset-2"
						{...props}
					>
						{parts.size === 1
							? PART_TITLE[entries[0].part]()
							: ucfirst(m.property_name_temperature())}
					</span>
				{/snippet}
			</Tooltip.Trigger>
			<Tooltip.Content>
				{regime === 'stellar'
					? m.tooltip_temperature_scale_stellar()
					: m.tooltip_temperature_scale()}
			</Tooltip.Content>
		</Tooltip.Root>

		<!-- Nobody has measured most of these bodies; the number is a radiative
		     equilibrium calculation and has to say so next to itself. -->
		{#if estimated}
			<Tooltip.Root>
				<Tooltip.Trigger>
					{#snippet child({ props })}
						<span
							class="text-muted-foreground/80 border-muted-foreground/30 w-fit cursor-help rounded border px-1 text-[0.65rem] uppercase"
							{...props}
						>
							{m.temperature_estimated()}
						</span>
					{/snippet}
				</Tooltip.Trigger>
				<Tooltip.Content>{m.tooltip_temperature_estimated()}</Tooltip.Content>
			</Tooltip.Root>
		{/if}
	</div>

	<!-- A quantitative axis: kept left-to-right in every locale so the gradient,
	     ticks and labels can't disagree about which end is cold. -->
	<div dir="ltr" class="flex flex-col gap-1">
		<div
			class="relative h-2.5 w-full rounded-full"
			style:background-image={gradient}
			bind:clientWidth={barWidth}
			aria-hidden="true"
		>
			<!-- Fade outside the body's range rather than tinting inside it, so the
			     stretch that carries the readings keeps its colour. -->
			{#if span}
				<span class="bg-background/65 absolute inset-y-0 left-0" style:width="{span.start}%"></span>
				<span class="bg-background/65 absolute inset-y-0 right-0" style:width="{100 - span.end}%"
				></span>
			{/if}
			{#each readings as reading (reading.label)}
				<span
					class="absolute -inset-y-0.5 w-[3px] -translate-x-1/2 rounded-full bg-white
						shadow-[0_0_0_1px_rgba(0,0,0,0.55)]"
					class:opacity-70={reading.kind !== 'mean'}
					style:left="{pos(reading.kelvin)}%"
				></span>
			{/each}
		</div>

		<div class="relative h-8 text-xs tabular-nums">
			{#each readings as reading, i (reading.label)}
				<!-- Name over value: "photosphere 5,772 K" on one line needs twice the room. -->
				<span
					class="absolute top-0 flex -translate-x-1/2 flex-col items-center whitespace-nowrap"
					class:text-foreground={reading.kind === 'mean'}
					class:text-muted-foreground={reading.kind !== 'mean'}
					style:left="{placed[i]}%"
				>
					<span class="opacity-60">{reading.label}</span>
					<span>{reading.text}</span>
				</span>
			{/each}
		</div>
	</div>
</div>
