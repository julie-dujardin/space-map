<script lang="ts">
	/**
	 * What the interior is still doing, under the cutaway that says what it is.
	 *
	 * One list rather than four, because the four tables behind it are four
	 * views of one question — is there heat left inside, and does it reach the
	 * surface. It opens with what the surface does, then reads backward: how
	 * much heat leaves, what supplies it, and what the core makes of it.
	 *
	 * Nearly every row is optional and most bodies show a handful. Five of the
	 * twenty-three — Europa, Callisto, Mimas, Dione, Charon — have a status and
	 * no numbers at all, which is the literature rather than a gap, so the list
	 * has to read as complete at two rows as it does at twenty.
	 *
	 * There are no headings, so every label names its own subject: "Volcanic
	 * eruptions a year", not "Eruptions a year" under a Volcanism heading. With
	 * two or three rows per table, headings would outnumber what they organise.
	 *
	 * The export carries more than this draws. Heat flux is left out as a
	 * restatement of heat output, and Io's Love numbers and the orbital
	 * resonances are in the block and deliberately not rendered — the resonance
	 * is an orbit fact rather than an interior one.
	 */
	import * as m from '$lib/paraglide/messages.js';
	import type { ActivityBlock, Measurement } from '$lib/fetch/objects/object-data';
	import {
		activitySummary,
		ageParts,
		dipoleMomentNote,
		fieldKindLabel,
		fieldParts,
		fieldStrengthNote,
		measurement,
		momentParts,
		type PartsOf,
		powerParts,
		qualifier,
		spellAge
	} from '$lib/format/activity';
	import { formatKm } from '$lib/format/distance';
	import { ltrIsolate } from '$lib/format/bidi';
	import Row from './kit/Row.svelte';
	import BodyRefLink from './kit/BodyRefLink.svelte';

	interface Props {
		activity: ActivityBlock;
	}

	let { activity }: Props = $props();

	// Digits, brackets and a Latin unit symbol reorder inside Arabic or Hebrew
	// text unless the run is isolated — the same treatment the layer cards give
	// their depths.
	const num = (value: Measurement, parts?: PartsOf) => ltrIsolate(measurement(value, parts));

	// Named styles included, unlike the Overview's line: this row is the whole
	// of what the volcanism and tectonics tables have to say about most bodies.
	let summary = $derived(activitySummary(activity, { everyStyle: true }));

	let volcanism = $derived(activity.volcanism);
	let tectonics = $derived(activity.tectonics);
	let tidal = $derived(activity.tidal);
	let magnetism = $derived(activity.magnetism);

	// Io and Enceladus publish the same watts as tidal power and as heat
	// leaving the body, because on those two the observed loss *is* taken as
	// the production. The exporter resolves that into one flag, so the panel
	// draws one row and says whose heat it is.
	let heat = $derived(volcanism?.endogenic_power_w ?? tidal?.power_w);
	let allTidal = $derived(tidal?.explains_heat_output === true);

	// Only a measured tide gets a row. `role` is the same quantity at five-rung
	// resolution, and "Minor" with nothing to be minor against said less than
	// nothing; a tide that has stopped is in the Activity line instead, where it
	// explains why the rest of that line is past tense.
	let measuredTide = $derived(
		!allTidal && volcanism?.endogenic_power_w ? tidal?.power_w : undefined
	);
</script>

{#if summary}
	<Row label={m.activity()} value={summary} />
{/if}

{#if volcanism}
	{#if volcanism.known_centres}
		<Row
			label={m.activity_volcanic_centres()}
			valueTooltip={qualifier(volcanism.known_centres)}
			value={num(volcanism.known_centres)}
		/>
	{/if}
	{#if volcanism.eruptions_per_year}
		<Row
			label={m.activity_eruptions_per_year()}
			valueTooltip={qualifier(volcanism.eruptions_per_year)}
			value={num(volcanism.eruptions_per_year)}
		/>
	{/if}
	{#if volcanism.erupted_volume_km3_per_year}
		<Row
			label={m.activity_erupted_volume()}
			valueTooltip={qualifier(volcanism.erupted_volume_km3_per_year)}
			value={m.activity_volume_rate({
				value: num(volcanism.erupted_volume_km3_per_year)
			})}
		/>
	{/if}
	{#if volcanism.plumes}
		<Row
			label={m.activity_plumes()}
			valueTooltip={qualifier(volcanism.plumes)}
			value={num(volcanism.plumes)}
		/>
	{/if}
	{#if volcanism.plume_mass_kg_per_s}
		<Row
			label={m.activity_plume_mass()}
			valueTooltip={qualifier(volcanism.plume_mass_kg_per_s)}
			value={m.activity_mass_rate({ value: num(volcanism.plume_mass_kg_per_s) })}
		/>
	{/if}
	{#if volcanism.youngest_activity_years}
		<Row
			label={m.activity_youngest_activity()}
			valueTooltip={spellAge(volcanism.youngest_activity_years.value)}
			value={num(volcanism.youngest_activity_years, ageParts)}
		/>
	{/if}
	{#if volcanism.surface_age_years}
		<Row
			label={m.activity_surface_age()}
			valueTooltip={spellAge(volcanism.surface_age_years.value)}
			value={num(volcanism.surface_age_years, ageParts)}
		/>
	{/if}
{/if}

{#if tectonics}
	{#if tectonics.radial_contraction_km}
		<Row
			label={m.activity_radial_contraction()}
			valueTooltip={qualifier(tectonics.radial_contraction_km)}
			value={ltrIsolate(formatKm(tectonics.radial_contraction_km.value))}
		/>
	{/if}
{/if}

{#if heat}
	<Row
		label={m.activity_heat_output()}
		valueTooltip={allTidal ? m.activity_heat_all_tidal() : qualifier(heat)}
		value={num(heat, powerParts)}
	/>
{/if}
{#if tidal}
	<Row label={m.activity_raised_by()}>
		<BodyRefLink id={tidal.raised_by} />
	</Row>
	{#if measuredTide}
		<Row
			label={m.activity_tidal_power()}
			valueTooltip={qualifier(measuredTide)}
			value={num(measuredTide, powerParts)}
		/>
	{/if}
{/if}

{#if magnetism}
	<Row label={m.activity_magnetic_field()} value={fieldKindLabel(magnetism.kind)} />
	{#if magnetism.surface_field_t}
		<Row
			label={m.activity_surface_field()}
			valueTooltip={fieldStrengthNote(magnetism.surface_field_t)}
			value={num(magnetism.surface_field_t, fieldParts)}
		/>
	{/if}
	{#if magnetism.dipole_moment_a_m2}
		<Row
			label={m.activity_dipole_moment()}
			valueTooltip={dipoleMomentNote(magnetism.dipole_moment_a_m2)}
			value={num(magnetism.dipole_moment_a_m2, momentParts)}
		/>
	{/if}
	{#if magnetism.dipole_tilt_deg}
		<Row
			label={m.activity_dipole_tilt()}
			valueTooltip={qualifier(magnetism.dipole_tilt_deg)}
			value={m.activity_degrees({ value: num(magnetism.dipole_tilt_deg) })}
		/>
	{/if}
	{#if magnetism.dynamo_ended_years}
		<Row
			label={m.activity_dynamo_ended()}
			valueTooltip={spellAge(magnetism.dynamo_ended_years.value)}
			value={num(magnetism.dynamo_ended_years, ageParts)}
		/>
	{/if}
{/if}
