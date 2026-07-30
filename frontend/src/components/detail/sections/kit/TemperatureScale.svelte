<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import * as Tooltip from '$lib/components/ui/tooltip/index.js';
	import type { TemperatureEntry, TemperaturePart } from '$lib/fetch/objects/object-data';
	import { ucfirst } from '$lib/format/quantities';
	import { formatStellarTemperature, formatTemperature } from '$lib/format/temperature';
	import { gradientStops, regimeFor, scalePosition } from '$lib/math/temperature-scale';

	interface Props {
		entries: TemperatureEntry[];
	}

	let { entries }: Props = $props();

	const PART_TITLE: Record<TemperaturePart, () => string> = {
		surface: m.temperature_of_surface,
		photosphere: m.temperature_of_photosphere,
		corona: m.temperature_of_corona,
		core: m.temperature_of_core
	};
	const PART_LABEL: Record<TemperaturePart, () => string> = {
		surface: m.temperature_part_surface,
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
	// Named by part when the body has several (the Sun's core vs photosphere),
	// otherwise by reading, which is the same information at one location.
	let flat = $derived(
		entries.flatMap((entry) =>
			(['min', 'mean', 'max'] as const)
				.filter((kind) => entry[kind] != null)
				.map((kind) => ({ part: entry.part, kind, quantity: entry[kind]! }))
		)
	);
	let byPart = $derived(entries.length > 1);
	let regime = $derived(regimeFor(flat.map((r) => r.quantity.value)));

	let readings = $derived(
		flat
			.map((r) => ({
				kind: r.kind,
				label: byPart ? PART_LABEL[r.part]() : READING_LABEL[r.kind](),
				kelvin: r.quantity.value,
				text:
					regime === 'stellar'
						? formatStellarTemperature(r.quantity)
						: formatTemperature(r.quantity)
			}))
			.sort((a, b) => a.kelvin - b.kelvin)
	);

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
	<Tooltip.Root>
		<Tooltip.Trigger>
			{#snippet child({ props })}
				<span
					class="text-muted-foreground w-fit cursor-help text-sm decoration-dotted underline underline-offset-2"
					{...props}
				>
					{entries.length === 1
						? PART_TITLE[entries[0].part]()
						: ucfirst(m.property_name_temperature())}
				</span>
			{/snippet}
		</Tooltip.Trigger>
		<Tooltip.Content>
			{regime === 'stellar' ? m.tooltip_temperature_scale_stellar() : m.tooltip_temperature_scale()}
		</Tooltip.Content>
	</Tooltip.Root>

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
