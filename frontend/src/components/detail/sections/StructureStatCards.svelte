<script lang="ts">
	/**
	 * The Structure tab's stat block: what standing there feels like, what it
	 * is under, and the one thing it is still doing. A headline, not a
	 * summary — the tab runs three charts deep, so a card may restate a row
	 * below.
	 *
	 * The third slot is best-first: watts where measured, then a magnetic
	 * field, then volcanism — numbers before categories, matching `ObjectStats`,
	 * so Mercury's and Ganymede's dynamos aren't thrown away for "extinct".
	 *
	 * A `none` field never takes the slot — that's a non-detection, not a
	 * field. Fewer than three cards is normal, not a gap; filler for the empty
	 * slot was tried and cut.
	 */
	import * as m from '$lib/paraglide/messages.js';
	import StatCardRow from './kit/StatCardRow.svelte';
	import type { Stat } from './kit/StatCard.svelte';
	import type { GlobalObjectData, Measurement } from '$lib/fetch/objects/object-data';
	import {
		fieldKindLabel,
		fieldParts,
		fieldStrengthNote,
		headline,
		measurement,
		type PartsOf,
		powerParts,
		qualifier,
		statusLabel,
		volcanismKindLabel
	} from '$lib/format/activity';
	import { formatEarthRatio, formatPressure, pressureLevelLabel } from '$lib/format/pressure';
	import { accelMs2, formatGees, formatMs2, gravityLabel } from '$lib/format/gravity';
	import { massKg } from '$lib/format/mass';
	import { meanRadiusKm } from '$lib/fetch/objects/physical';
	import { ucfirst } from '$lib/format/quantities';
	import { ltrIsolate } from '$lib/format/bidi';
	import { G_KM3_KG_S2 } from '$lib/math/travel/constants';

	interface Props {
		global: GlobalObjectData | null;
	}
	let { global }: Props = $props();

	// Gees rather than the published m/s²: the card answers what standing there
	// feels like, and the SI reading goes to the tooltip. GM/r² stands in where
	// nothing is published — most small bodies with a mass.
	let gravityStat = $derived.by<Stat | null>(() => {
		const published = global?.wikidata?.surface_gravity;
		const ms2 = (published ? accelMs2(published) : null) ?? derivedMs2();
		if (ms2 === null || ms2 <= 0) return null;
		return {
			label: gravityLabel(global),
			value: ltrIsolate(formatGees(ms2)),
			tooltip: ltrIsolate(formatMs2(ms2))
		};
	});

	function derivedMs2(): number | null {
		const mass = global?.sbdb?.mass ?? global?.wikidata?.mass;
		const kg = mass ? massKg(mass) : null;
		if (kg === null) return null;
		const radiusKm = meanRadiusKm(global);
		if (radiusKm == null || radiusKm <= 0) return null;
		return ((G_KM3_KG_S2 * kg) / (radiusKm * radiusKm)) * 1000;
	}

	// Labelled by the level it is quoted at, the way the Overview's row is: a
	// figure at Saturn's cloud deck and one at Mars's datum are not the same
	// claim, and neither is a surface pressure.
	let pressureStat = $derived.by<Stat | null>(() => {
		const pressure = global?.atmosphere?.pressure;
		if (!pressure) return null;
		return {
			label: pressureLevelLabel(pressure.level),
			value: ltrIsolate(
				`${pressure.qualifier === 'upper_limit' ? '<' : '≈'} ${formatPressure(pressure.pa)}`
			),
			tooltip: formatEarthRatio(pressure.pa) ?? undefined
		};
	});

	/** The card's own line, plus what the short form had to leave out: the full
	 *  reading where a width was dropped, then what the source said about it. */
	function reading(
		value: Measurement,
		parts: PartsOf,
		{ note }: { note?: string } = {}
	): Pick<Stat, 'value' | 'tooltip'> {
		const short = headline(value, parts);
		const full = measurement(value, parts);
		const tooltip = [full === short ? null : full, note].filter(Boolean).join(' — ');
		return { value: ltrIsolate(short), tooltip: tooltip || undefined };
	}

	let activityStat = $derived.by<Stat | null>(() => {
		const activity = global?.activity;
		const magnetism = activity?.magnetism;
		const volcanism = activity?.volcanism;

		// Io and Enceladus quote the same watts as tidal power and as heat leaving
		// the body; the exporter flags which, and the card takes the tidal label
		// instead of saying in a tooltip what it could say on the front.
		const heat = volcanism?.endogenic_power_w ?? activity?.tidal?.power_w;
		if (heat) {
			const allTidal = activity?.tidal?.explains_heat_output === true;
			return {
				label: allTidal ? m.activity_tidal_power() : m.activity_heat_output(),
				...reading(heat, powerParts, { note: allTidal ? undefined : qualifier(heat) })
			};
		}

		// What kind of field it is stays in the row below — on the card it is the
		// published width and what the number comes to against Earth, which are
		// the two things the one line had to leave out.
		const field = magnetism && magnetism.kind !== 'none' ? magnetism.surface_field_t : undefined;
		if (magnetism && field) {
			return {
				label: m.activity_magnetic_field(),
				...reading(field, fieldParts, { note: fieldStrengthNote(field) })
			};
		}

		// The kind on the label and the rung under it, so the card never reads
		// "Volcanism: Volcanism" the way a row once did. Both vocabularies are
		// written to sit inside a sentence — "Volcanism (probable)" — so a card,
		// which is the whole sentence, has to capitalize them itself.
		if (volcanism)
			return {
				label: volcanismKindLabel(volcanism.kind),
				value: ucfirst(statusLabel(volcanism.status))
			};

		// An induced field has no strength of its own — it is the parent's, bent.
		if (magnetism && magnetism.kind !== 'none')
			return { label: m.activity_magnetic_field(), value: fieldKindLabel(magnetism.kind) };

		return null;
	});

	let cards = $derived([gravityStat, pressureStat, activityStat].filter((s) => s !== null));
</script>

<StatCardRow stats={cards} />
