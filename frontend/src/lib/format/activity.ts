/**
 * Rendering for the activity block — what a body is still doing.
 *
 * Every quantity picks its unit through a `PartsOf`, whether the unit changes
 * with the magnitude (GW to TW, nT to µT, ka to Ga) or is the only one the
 * quantity is ever quoted in (kg/s, km³/yr, degrees). One shape for both, so
 * `measurement` punctuates every row the same way — the fixed units used to
 * wrap the finished string in a message of their own and came out
 * "200 (170–230) kg/s" next to "15.8 GW (12.7–18.9 GW)".
 *
 * Every value goes through `measurement`, because in this subject the
 * qualifier is usually the finding: a bound and a measurement would otherwise
 * draw identically, and Titan's magnetic moment has only ever been a bound.
 */
import * as m from '$lib/paraglide/messages.js';
import { getLocale } from '$lib/paraglide/runtime.js';
import type {
	ActivityBlock,
	MagneticField,
	Measurement,
	Volcanism
} from '$lib/fetch/objects/object-data';
import { ltrIsolate } from './bidi';
import {
	earthRatio,
	formatSpan,
	joinParts,
	scientificNotation,
	sigFigures,
	ucfirst,
	type PartsOf
} from './quantities';

export type { PartsOf };

/**
 * A number with no unit — a count, a Love number, a fraction of a radius.
 *
 * Counts keep every digit: GVP's catalogue holds 1,196 volcanoes, and three
 * significant figures would publish 1,200 as though the last two were unknown.
 * Anything below a thousandth goes scientific instead — Ceres extrudes 10⁻⁵ km³
 * of brine a year, which as a decimal is a row of zeros.
 */
const bare: PartsOf = (value) => {
	if (Number.isInteger(value)) {
		return { value: new Intl.NumberFormat(getLocale()).format(value), unit: '' };
	}
	return {
		value: Math.abs(value) >= 1e-3 ? sigFigures(value) : scientificNotation(value),
		unit: ''
	};
};

// These symbols come from the hand-written `symbol_*` messages rather than
// through `formatUnit`, whose `unit_symbol_*` namespace is generated from
// Wikidata and would render "47 terawatt" until an export refreshed it. They
// are also the units where the *prefix* inflects — micro is мк in Russian — so
// there is one key per prefixed unit, the same shape the generated ones take.

/** Heat leaving a body, from Enceladus's 15.8 GW to Io's 105 TW. */
export const powerParts: PartsOf = (w) => {
	if (w >= 1e12) return { value: sigFigures(w / 1e12), unit: m.symbol_terawatt() };
	if (w >= 1e9) return { value: sigFigures(w / 1e9), unit: m.symbol_gigawatt() };
	return { value: sigFigures(w), unit: m.symbol_watt() };
};

/** Surface fields run from Titan's 0.78 nT bound to Jupiter's 418 µT. */
export const fieldParts: PartsOf = (tesla) =>
	tesla >= 1e-6
		? { value: sigFigures(tesla * 1e6), unit: m.symbol_microtesla() }
		: { value: sigFigures(tesla * 1e9), unit: m.symbol_nanotesla() };

// The quantities with one unit at every magnitude. They still go through
// `PartsOf` rather than a message that swallows the figure, so a published
// width is bracketed the way every other row's is.

/** What Enceladus's plumes lift, in kg/s. */
export const massRateParts: PartsOf = (kgPerSecond) => ({
	value: bare(kgPerSecond).value,
	unit: m.symbol_kilogram_per_second()
});

/** What a body extrudes in a year, in km³. */
export const volumeRateParts: PartsOf = (km3PerYear) => ({
	value: bare(km3PerYear).value,
	unit: m.symbol_cubic_kilometre_per_year()
});

/** An angle — the tilt between a magnetic axis and a rotation axis. */
export const degreeParts: PartsOf = (degrees) => ({
	value: bare(degrees).value,
	unit: m.symbol_degree(),
	tight: true
});

// Geologists' notation, and the only one that fits a stat cell: "53 ka" against
// "53 thousand years ago". Not localized because ka/Ma/Ga are symbols rather
// than words — the row's tooltip spells it out in the reader's language.
const AGE_UNITS: [number, string][] = [
	[1e9, 'Ga'],
	[1e6, 'Ma'],
	[1e3, 'ka']
];

/**
 * A dipole moment in its own units, which is a 27-digit number on Jupiter.
 *
 * There is no prefixed form anyone uses — planetary magnetism publishes
 * gauss·R³ and leaves A m² to be worked out — so this is the one quantity that
 * stays in scientific notation at every magnitude rather than picking a prefix.
 */
export const momentParts: PartsOf = (value) => ({
	value: scientificNotation(value, 3),
	unit: m.symbol_ampere_square_metre()
});

/** Years before present. */
export const ageParts: PartsOf = (years) => {
	for (const [scale, unit] of AGE_UNITS) {
		if (years >= scale) return { value: sigFigures(years / scale), unit };
	}
	return { value: sigFigures(years), unit: 'a' };
};

/** The same age in words, for the tooltip that unpacks "3.5 Ga". */
export function spellAge(years: number): string {
	if (years >= 1e9) return m.activity_age_billion_years({ value: sigFigures(years / 1e9) });
	if (years >= 1e6) return m.activity_age_million_years({ value: sigFigures(years / 1e6) });
	return m.activity_age_thousand_years({ value: sigFigures(years / 1e3) });
}

/**
 * One measurement as the panel draws it: "47 TW (45–49 TW)", "< 0.78 nT".
 *
 * The published width rides in parentheses rather than as a ± because it
 * usually is not one — Venus's surface age is 250 Ma to 1 Ga across crater
 * models, and the value is the middle of that claim rather than a best fit.
 * A bound gets its "<" and no width; a bound with a width would be two
 * different statements about the same non-detection.
 */
export function measurement(value: Measurement, parts: PartsOf = bare): string {
	const text = headline(value, parts);
	if (value.upper_limit || !value.range) return text;
	const [low, high] = value.range.map(parts);
	return `${text} (${formatSpan(low, high)})`;
}

/**
 * The same measurement with its width dropped — the stat cards' form.
 *
 * A card is one short line, and Jupiter's field is published 320 µT to 2 mT:
 * the full form wraps to three lines in a card 115 px wide. The width is not
 * lost, it moves to the tooltip, where the card shows the whole reading exactly
 * as the row below does. The bound stays, because "<" is what the number *is*.
 */
export function headline(value: Measurement, parts: PartsOf = bare): string {
	const text = joinParts(parts(value.value));
	return value.upper_limit ? `< ${text}` : text;
}

/**
 * What the source said about the number, for the row label's tooltip.
 *
 * `modelled` is the one that changes what a reader should conclude: Venus's
 * 120 eruptions a year is Earth's record scaled by mass, and next to Earth's
 * own 79.2 it would otherwise read as the same kind of fact. `as_of` is the
 * survey a count belongs to, and stays in the source's English — it names an
 * instrument and a date rather than saying anything.
 */
export function qualifier(value: Measurement): string | undefined {
	const notes = [
		value.modelled ? m.activity_modelled() : null,
		value.as_of ?? null,
		value.upper_limit ? m.activity_upper_limit() : null
	].filter(Boolean);
	return notes.length ? notes.join(' — ') : undefined;
}

const VOLCANISM_KIND: Record<string, () => string> = {
	silicate: m.activity_kind_silicate,
	cryo: m.activity_kind_cryo,
	both: m.activity_kind_both,
	none: m.activity_kind_none
};

const STATUS: Record<string, () => string> = {
	active: m.activity_status_active,
	probable: m.activity_status_probable,
	suspected: m.activity_status_suspected,
	dormant: m.activity_status_dormant,
	extinct: m.activity_status_extinct,
	none: m.activity_status_none
};

const TECTONIC_STYLE: Record<string, () => string> = {
	plate_tectonics: m.activity_style_plate_tectonics,
	stagnant_lid: m.activity_style_stagnant_lid,
	contractional_lid: m.activity_style_contractional_lid,
	mobile_lid: m.activity_style_mobile_lid,
	ice_shell_tectonics: m.activity_style_ice_shell_tectonics,
	impact_dominated: m.activity_style_impact_dominated,
	none: m.activity_style_none
};

const FIELD_KIND: Record<string, () => string> = {
	dynamo: m.activity_field_dynamo,
	induced: m.activity_field_induced,
	remanent: m.activity_field_remanent,
	none: m.activity_field_none
};

export function statusLabel(status: string): string {
	return STATUS[status]?.() ?? status;
}

/**
 * What the tide does for this body's heat budget, at the five-rung resolution
 * its sources commit to.
 *
 * The body panel deliberately has no such row — "Minor" with nothing to be
 * minor against says less than nothing. On the collection page there is
 * something: ten other bodies on the same list, three of them with a wattage,
 * and the rung is what orders the eight that have none.
 */
const TIDAL_ROLE: Record<string, () => string> = {
	dominant: m.tidal_role_dominant,
	significant: m.tidal_role_significant,
	minor: m.tidal_role_minor,
	negligible: m.tidal_role_negligible,
	past: m.tidal_role_past
};

export function tidalRoleLabel(role: string): string {
	return TIDAL_ROLE[role]?.() ?? role;
}

export function tectonicStyleLabel(style: string): string {
	return TECTONIC_STYLE[style]?.() ?? style;
}

export function fieldKindLabel(kind: string): string {
	return FIELD_KIND[kind]?.() ?? kind;
}

/**
 * "Volcanism", "Cryovolcanism (suspected)" — the thing and how sure anyone is.
 *
 * `active` is the only rung that goes unqualified, because it is the one that
 * means what the bare noun means. Every other rung is an argument about
 * whether the noun applies, and dropping it would turn Venus's case into
 * Earth's fact.
 */
/** Takes only what it reads, so a collection row — which carries the kind and
 *  the status but none of the measurements — can use it too. */
export function volcanismLabel(volcanism: Pick<Volcanism, 'kind' | 'status'>): string {
	const kind = volcanismKindLabel(volcanism.kind);
	if (volcanism.status === 'active') return kind;
	return m.activity_qualified({ value: kind, status: statusLabel(volcanism.status) });
}

/** The bare noun, for where the status is said somewhere else — a stat card
 *  puts the kind on the label and the rung underneath it. */
export function volcanismKindLabel(kind: string): string {
	return VOLCANISM_KIND[kind]?.() ?? kind;
}

/**
 * Volcanism and tectonics as one line — "Volcanism, plate tectonics".
 *
 * They share a row because separately they read as a tautology: a row labelled
 * Volcanism whose value is "Volcanism" tells Io nothing. Volcanism leads
 * wherever a body has it, and where there is no volcanism entry at all the tide
 * is the only thing happening and says so — that is Mimas and Dione, whose
 * oceans are the whole reason they are in the table.
 *
 * A tide that has already run its course joins the line, because it is the
 * reason the rest of the row is in the past tense — Ganymede's grooves, Triton's
 * young surface and Charon's Vulcan Planitia are all the record of a tide that
 * stopped. A tide still running says nothing here: there is a heat row for the
 * three bodies whose watts anyone has measured, and for the rest the five-rung
 * role was never worth a line of its own.
 *
 * `everyStyle` decides whether a lithosphere nobody has caught moving still
 * gets named. The Overview leaves it out, where a second clause would read as a
 * second live process; the Structure tab names it with its status, because
 * there the row is the whole of what the tectonics table has to say.
 */
export function activitySummary(
	activity: ActivityBlock | undefined,
	{ everyStyle = false }: { everyStyle?: boolean } = {}
): string | null {
	if (!activity) return null;
	const clauses: string[] = [];
	if (activity.volcanism) clauses.push(volcanismLabel(activity.volcanism));
	const tectonics = activity.tectonics;
	if (tectonics && (everyStyle || tectonics.status === 'active')) {
		const style = tectonicStyleLabel(tectonics.style).toLocaleLowerCase(getLocale());
		clauses.push(
			tectonics.status === 'active'
				? style
				: m.activity_qualified({ value: style, status: statusLabel(tectonics.status) })
		);
	}
	if (activity.tidal?.role === 'past') {
		const past = m.activity_tidally_heated_past();
		clauses.push(clauses.length ? past.toLocaleLowerCase(getLocale()) : past);
	}
	if (!clauses.length && activity.tidal) clauses.push(m.activity_tidally_heated());
	if (!clauses.length) return null;
	// Sentence case on the joined line, not on each clause: the styles are
	// lowercased to sit after the volcanism, and a body with tectonics and no
	// volcanism would otherwise open the row in lower case.
	return ucfirst(new Intl.ListFormat(getLocale(), { style: 'long', type: 'unit' }).format(clauses));
}

/**
 * The Overview's magnetic line: what kind of field, and how big where a body
 * has a number for it. A dynamo with no strength is Io's disputed induction
 * and Callisto's ocean signature, where the finding is that there is one.
 */
export function fieldSummary(magnetism: MagneticField | undefined): string | null {
	if (!magnetism) return null;
	const kind = fieldKindLabel(magnetism.kind);
	const strength = magnetism.surface_field_t;
	if (!strength || magnetism.kind === 'none') return kind;
	return `${kind} · ${ltrIsolate(headline(strength, fieldParts))}`;
}

/**
 * A dipole moment against Earth's, which is the only way this number reads.
 * 1.53×10²⁷ A m² says nothing; 20,000 times Earth's says the whole thing.
 * Earth itself gets nothing back from the comparison, so its row is dropped
 * and its surface field carries the magnitude instead.
 */
const EARTH_DIPOLE_MOMENT_A_M2 = 7.69e22;
const EARTH_SURFACE_FIELD_T = 2.9733e-5;

function vsEarth(value: Measurement, earth: number): string | null {
	const text = earthRatio(value.value / earth);
	if (text === null) return null;
	return value.upper_limit ? `< ${text}` : text;
}

/**
 * The tooltip for a magnetic number: what it comes to against Earth, then
 * whatever the source said about it.
 *
 * Both rows carry one, and they are deliberately different ratios. Jupiter's
 * field is ~14× Earth's where you would float, while its moment is ~20,000× —
 * the gap between the two is Jupiter's size, and neither number says it alone.
 * Earth gets no comparison with itself, only the source's own words.
 */
function earthNote(value: Measurement, earth: number): string | undefined {
	const notes = [vsEarth(value, earth), qualifier(value)].filter(Boolean);
	return notes.length ? notes.join(' — ') : undefined;
}

export function fieldStrengthNote(value: Measurement): string | undefined {
	return earthNote(value, EARTH_SURFACE_FIELD_T);
}

export function dipoleMomentNote(value: Measurement): string | undefined {
	return earthNote(value, EARTH_DIPOLE_MOMENT_A_M2);
}
