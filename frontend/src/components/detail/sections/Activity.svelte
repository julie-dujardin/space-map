<script module lang="ts">
	/**
	 * One list rather than four tables, since volcanism/tectonics/tidal/
	 * magnetism are four views of one question — is there heat left inside,
	 * and does it reach the surface.
	 *
	 * Most rows are optional; some bodies show only a status with no numbers,
	 * which is the literature rather than a gap. No headings, so every label
	 * names its own subject instead.
	 *
	 * Heat flux is left out as a restatement of heat output; Io's Love numbers
	 * and resonances are orbit facts, not interior ones.
	 */
	import * as m from '$lib/paraglide/messages.js';
	import type { ActivityBlock, Measurement } from '$lib/fetch/objects/object-data';
	import {
		activitySummary,
		ageParts,
		degreeParts,
		dipoleMomentNote,
		fieldKindLabel,
		fieldParts,
		fieldStrengthNote,
		massRateParts,
		measurement,
		momentParts,
		type PartsOf,
		powerParts,
		qualifier,
		spellAge,
		volumeRateParts
	} from '$lib/format/activity';
	import { formatKm } from '$lib/format/distance';
	import { ltrIsolate } from '$lib/format/bidi';

	interface ActivityRow {
		/** Reads the whole block, so a row that names its own subject can decide
		 *  from the same source it states. */
		label: (a: ActivityBlock) => string;
		/** The figure, formatted; undefined leaves the row out. */
		value?: (a: ActivityBlock) => string | undefined;
		/** What this particular figure is: its qualifier, what it comes to
		 *  against Earth, how long ago it is in words. */
		note?: (a: ActivityBlock) => string | undefined;
		/** The one row whose value is another body, rendered as a link to it. */
		ref?: (a: ActivityBlock) => string | undefined;
	}

	// Digits, brackets and a Latin unit symbol reorder inside Arabic or Hebrew
	// text unless the run is isolated — the same treatment the layer cards give
	// their depths.
	const num = (value: Measurement, parts?: PartsOf) => ltrIsolate(measurement(value, parts));

	/** A row stating one published measurement. */
	function measured(
		label: () => string,
		get: (a: ActivityBlock) => Measurement | undefined,
		parts?: PartsOf,
		note: (value: Measurement) => string | undefined = qualifier
	): ActivityRow {
		return {
			label,
			value: (a) => {
				const value = get(a);
				return value ? num(value, parts) : undefined;
			},
			note: (a) => {
				const value = get(a);
				return value ? note(value) : undefined;
			}
		};
	}

	// Io and Enceladus publish the same watts as tidal power and as heat leaving
	// the body, because on those two the observed loss *is* taken as the
	// production. The exporter resolves that into one flag, so the panel draws
	// one row under the tidal label rather than two identical ones.
	const heat = (a: ActivityBlock) => a.volcanism?.endogenic_power_w ?? a.tidal?.power_w;
	const allTidal = (a: ActivityBlock) => a.tidal?.explains_heat_output === true;

	// Only a measured tide gets a row of its own. `role` is the same quantity at
	// five-rung resolution, and "Minor" with nothing to be minor against said
	// less than nothing; a tide that has stopped is in the Activity line
	// instead, where it explains why the rest of that line is past tense.
	function measuredTide(a: ActivityBlock): Measurement | undefined {
		if (allTidal(a)) return undefined;
		return a.volcanism?.endogenic_power_w ? a.tidal?.power_w : undefined;
	}

	const ROWS: ActivityRow[] = [
		measured(m.activity_volcanic_centres, (a) => a.volcanism?.known_centres),
		measured(m.activity_eruptions_per_year, (a) => a.volcanism?.eruptions_per_year),
		measured(
			m.activity_erupted_volume,
			(a) => a.volcanism?.erupted_volume_km3_per_year,
			volumeRateParts
		),
		measured(m.activity_plumes, (a) => a.volcanism?.plumes),
		measured(m.activity_plume_mass, (a) => a.volcanism?.plume_mass_kg_per_s, massRateParts),
		measured(
			m.activity_youngest_activity,
			(a) => a.volcanism?.youngest_activity_years,
			ageParts,
			(value) => spellAge(value.value)
		),
		measured(
			m.activity_surface_age,
			(a) => a.volcanism?.surface_age_years,
			ageParts,
			(value) => spellAge(value.value)
		),
		// Kilometres of lost radius, not a rate — the only row the measurement
		// formatter has nothing to add to.
		{
			label: m.activity_radial_contraction,
			value: (a) => {
				const value = a.tectonics?.radial_contraction_km;
				return value ? ltrIsolate(formatKm(value.value)) : undefined;
			},
			note: (a) => {
				const value = a.tectonics?.radial_contraction_km;
				return value ? qualifier(value) : undefined;
			}
		},
		// Named for what it is where the two are the same number: on Io and
		// Enceladus the row *is* the tidal heating, so the label says so and there
		// is nothing left for a tooltip to explain.
		{
			label: (a) => (allTidal(a) ? m.activity_tidal_power() : m.activity_heat_output()),
			value: (a) => {
				const value = heat(a);
				return value ? num(value, powerParts) : undefined;
			},
			note: (a) => {
				const value = heat(a);
				return value && !allTidal(a) ? qualifier(value) : undefined;
			}
		},
		{ label: m.activity_raised_by, ref: (a) => a.tidal?.raised_by },
		measured(m.activity_tidal_power, measuredTide, powerParts),
		{
			label: m.activity_magnetic_field,
			value: (a) => (a.magnetism ? fieldKindLabel(a.magnetism.kind) : undefined)
		},
		measured(
			m.activity_surface_field,
			(a) => a.magnetism?.surface_field_t,
			fieldParts,
			fieldStrengthNote
		),
		measured(
			m.activity_dipole_moment,
			(a) => a.magnetism?.dipole_moment_a_m2,
			momentParts,
			dipoleMomentNote
		),
		measured(m.activity_dipole_tilt, (a) => a.magnetism?.dipole_tilt_deg, degreeParts),
		measured(
			m.activity_dynamo_ended,
			(a) => a.magnetism?.dynamo_ended_years,
			ageParts,
			(value) => spellAge(value.value)
		)
	];
</script>

<script lang="ts">
	import Row from './kit/Row.svelte';
	import BodyRefLink from './kit/BodyRefLink.svelte';

	interface Props {
		activity: ActivityBlock;
	}

	let { activity }: Props = $props();

	// Named styles included, unlike the Overview's line: this row is the whole
	// of what the volcanism and tectonics tables have to say about most bodies.
	let summary = $derived(activitySummary(activity, { everyStyle: true }));
</script>

{#if summary}
	<Row label={m.activity()} value={summary} />
{/if}

{#each ROWS as row, i (i)}
	{@const ref = row.ref?.(activity)}
	{@const value = row.value?.(activity)}
	{#if ref !== undefined}
		<Row label={row.label(activity)}>
			<BodyRefLink id={ref} />
		</Row>
	{:else if value !== undefined}
		<Row label={row.label(activity)} valueTooltip={row.note?.(activity)} {value} />
	{/if}
{/each}
