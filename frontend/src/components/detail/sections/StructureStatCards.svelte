<script lang="ts">
	/**
	 * The Structure tab's stat block: how much body there is, what it is under,
	 * and the one thing it is still doing.
	 *
	 * The tab runs three screens deep — two charts, a composition bar and a
	 * table of layer cards — so this is a headline rather than a summary of the
	 * panel immediately below it, and it may restate a row a reader would
	 * otherwise have to scroll to.
	 *
	 * The first two slots are fixed. The third is whatever this body has to show
	 * for itself, best-first: watts where anyone has measured the heat leaving
	 * it, then a magnetic field, then volcanism. Numbers before categories, the
	 * order `ObjectStats` uses — strict volcanism-first would spend Mercury's and
	 * Ganymede's card on the word "extinct" and throw away the dynamos, which on
	 * both bodies are the interesting thing.
	 *
	 * A `none` field never takes the slot: Titan's 0.78 nT is the tightness of a
	 * non-detection rather than a field. What kind of field it is — Mars's 2 µT
	 * is magnetised crust, not a dipole — is the row's job in the section below.
	 *
	 * Fewer than three cards is the normal case, not a gap: fifteen of the
	 * thirty-two bodies have no atmosphere to quote a pressure at, and the ten
	 * mid-sized icy moons nobody has measured anything else on show mass alone.
	 * There is deliberately no filler for that slot — a card reading
	 * "Differentiated" on nine of those ten was tried and cut.
	 */
	import * as m from '$lib/paraglide/messages.js';
	import * as Tooltip from '$lib/components/ui/tooltip/index.js';
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
	import { formatMassKg, massEarthNote, massKg } from '$lib/format/mass';
	import { ucfirst } from '$lib/format/quantities';
	import { ltrIsolate } from '$lib/format/bidi';

	interface Props {
		global: GlobalObjectData | null;
	}
	let { global }: Props = $props();

	interface Stat {
		label: string;
		value: string;
		tooltip?: string;
	}

	// Kilograms rather than the export's per-body unit: "5.97 Rg" on Earth beside
	// "318 M⊕" on Jupiter is three scales across three neighbouring pages, and
	// neither symbol means anything on sight. The ruler is in the tooltip.
	let massStat = $derived.by<Stat | null>(() => {
		const mass = global?.sbdb?.mass ?? global?.wikidata?.mass;
		const kg = mass ? massKg(mass) : null;
		if (kg === null) return null;
		return {
			label: m.property_name_mass(),
			value: ltrIsolate(formatMassKg(kg)),
			tooltip: massEarthNote(kg)
		};
	});

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

	let cards = $derived([massStat, pressureStat, activityStat].filter((s) => s !== null));
</script>

{#if cards.length > 0}
	<div class="grid auto-cols-fr grid-flow-col gap-2">
		{#each cards as s (s.label)}
			<div
				class="border-border/60 bg-muted/40 flex flex-col gap-1 rounded-md border p-2.5 {s.tooltip
					? 'cursor-help'
					: ''}"
			>
				<div class="text-muted-foreground text-[10px] uppercase">{s.label}</div>
				<!-- Anchored on the value, never the label: each of these says
				     something about this particular number — what it comes to against
				     Earth, which survey it belongs to, whether it is a bound. -->
				{#if s.tooltip}
					<Tooltip.Root>
						<Tooltip.Trigger>
							{#snippet child({ props })}
								<div class="text-sm font-semibold tabular-nums" {...props}>{s.value}</div>
							{/snippet}
						</Tooltip.Trigger>
						<Tooltip.Content>{s.tooltip}</Tooltip.Content>
					</Tooltip.Root>
				{:else}
					<div class="text-sm font-semibold tabular-nums">{s.value}</div>
				{/if}
			</div>
		{/each}
	</div>
{/if}
