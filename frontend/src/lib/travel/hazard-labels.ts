/**
 * How a hazard is written down.
 *
 * Shared by the row of trajectories, the detail below it and the map's chip,
 * so the same hazard reads the same way wherever it turns up. Kept separate
 * from `hazards.ts`, which knows nothing about a locale, and imports only the
 * hazard *types* from it so the map isn't dragged into the trajectory kernel.
 */

import * as m from '$lib/paraglide/messages.js';
import { ltrIsolate, quantityIsolate } from '$lib/format/bidi';
import { lengthParts, smallLengthParts } from '$lib/format/distance';
import { formatDurationNarrow, SECONDS_PER_DAY } from '$lib/format/duration';
import { formatJoules, formatJoulesWithTnt } from '$lib/format/energy';
import {
	asPercent,
	fixed,
	formatPercent,
	joinParts,
	joinPartsNoBreak,
	percentParts,
	sigFigures,
	spanFields
} from '$lib/format/quantities';
import { formatKelvin } from '$lib/format/temperature';
// Leaf modules, not the `$lib/math/travel` barrel. This file is on the map's
// chunk, and the barrel brings the trajectory solvers with it.
import { MEASURED_GRAIN_RADIUS_M } from '$lib/math/travel/dust';
import {
	BELT_MODEL_UNCERTAINTY_FACTOR,
	cancerRiskFraction,
	lethalDoseFraction
} from '$lib/math/travel/radiation';
import { CONCRETE_CAP_M, ISS_DOSE_SV_PER_DAY, type RadiationShield } from '$lib/math/travel/shield';
import type { AdjustedHazard, Hazard, HazardKind, LabelledHazard } from './hazards';
import { equilibriumTempK } from './sunlight';
import { formatDv, formatDvBrief, formatGray, formatSievert } from './format';

/** Significant figures of a hazard figure. The models are not more accurate. */
const DIGITS = 2;

/** Sunlight as a percentage, with the sign of the locale. Whole numbers from
 *  10%, two significant figures below. */
function percent(fraction: number): string {
	const value = fraction * 100;
	return joinParts(asPercent(value >= 10 ? fixed(value, 0) : sigFigures(value, DIGITS)));
}

/** The diameter of a grain. The model gives a radius, which would read as the size. */
function grainSize(radiusM: number): string {
	return joinPartsNoBreak(smallLengthParts(2 * radiusM, DIGITS));
}

/** A lag rounded to the minute once it is minutes — the seconds are false
 *  precision, and "49m 56s" reads as a measurement rather than a scale. */
function lag(seconds: number): string {
	return formatDurationNarrow(roundLag(seconds) / SECONDS_PER_DAY);
}

function roundLag(seconds: number): number {
	return seconds >= 60 ? Math.round(seconds / 60) * 60 : seconds;
}

/** The four texts a hazard needs: its name, the chip beside the arc, the figure
 *  on a detail row, and the sentence under it. */
interface HazardText {
	name(): string;
	chip(hazard: Hazard): string;
	value(hazard: Hazard): string;
	detail(hazard: Hazard, originName: string, bodyName: string): string;
}

/**
 * Every wording of a hazard together, so the four are read and edited as one.
 *
 * The icons stay in `hazard-style.ts`: they pull in the icon library, and this
 * file is on the map's chunk.
 */
const HAZARD_TEXT: Record<HazardKind, HazardText> = {
	'solar-heat': {
		name: m.travel_hazard_heat,
		chip: (hazard) => m.travel_hazard_heat_chip({ value: sigFigures(hazard.peak, DIGITS) }),
		value: (hazard) => m.travel_hazard_heat_value({ value: sigFigures(hazard.peak, DIGITS) }),
		detail: (hazard) =>
			m.travel_hazard_heat_detail({
				au: ltrIsolate(fixed(hazard.auAtPeak ?? 0, 2)),
				temp: formatKelvin(equilibriumTempK(hazard.auAtPeak ?? 1))
			})
	},
	'solar-power': {
		name: m.travel_hazard_power,
		chip: (hazard) => m.travel_hazard_power_chip({ value: percent(hazard.peak) }),
		value: (hazard) => m.travel_hazard_power_value({ value: percent(hazard.peak) }),
		detail: (hazard) =>
			m.travel_hazard_power_detail({
				au: ltrIsolate(fixed(hazard.auAtPeak ?? 0, 1)),
				value: ltrIsolate(percent(hazard.peak))
			})
	},
	conjunction: {
		name: m.travel_hazard_conjunction,
		chip: () => m.travel_hazard_conjunction_chip(),
		value: (hazard) => m.travel_hazard_conjunction_value({ value: fixed(hazard.peak, 1) }),
		detail: (_hazard, originName) => m.travel_hazard_conjunction_detail({ origin: originName })
	},
	'signal-lag': {
		name: m.travel_hazard_lag,
		chip: (hazard) => m.travel_hazard_lag_chip({ value: lag(hazard.peak) }),
		value: (hazard) => m.travel_hazard_lag_value({ value: lag(hazard.peak) }),
		// Round trip, not the one-way figure beside it. Doubled after rounding,
		// so it cannot read as an odd multiple of the figure above it.
		detail: (hazard) =>
			m.travel_hazard_lag_detail({
				value: ltrIsolate(formatDurationNarrow((roundLag(hazard.peak) * 2) / SECONDS_PER_DAY))
			})
	},
	aeroassist: {
		name: m.travel_hazard_aero,
		chip: (hazard) => m.travel_hazard_aero_chip({ value: formatDvBrief(hazard.peak) }),
		value: (hazard) => formatDv(hazard.peak),
		detail: (hazard) => m.travel_hazard_aero_detail({ value: formatDv(hazard.peak) })
	},
	radiation: {
		name: m.travel_hazard_radiation,
		chip: (hazard) => formatSievert(hazard.peak),
		value: (hazard) => formatSievert(hazard.peak),
		// The rate and the total. One sievert over nine years is a different
		// problem from one sievert in eight months. The reference dose includes
		// the aluminium of a hull. The check on the lunar surface puts its effect
		// under 10%.
		detail: (hazard) => {
			const value = ltrIsolate(formatSievert(hazard.rateAtPeak ?? 0));
			const risk = cancerRiskFraction(hazard.peak);
			if (!hazard.shipTime) {
				return m.travel_hazard_radiation_detail({ value, risk: ltrIsolate(formatPercent(risk)) });
			}
			// The linear risk model gives more than 100% past about 24 Sv.
			return risk < 1
				? m.travel_hazard_radiation_ship_detail({ value, risk: ltrIsolate(formatPercent(risk)) })
				: m.travel_hazard_radiation_ship_past_model({ value });
		}
	},
	'belt-crossing': {
		name: m.travel_hazard_belt,
		chip: (hazard) =>
			hazard.unpriced ? m.travel_hazard_belt_unpriced_chip() : formatGray(hazard.peak),
		value: (hazard) =>
			hazard.unpriced ? m.travel_hazard_belt_unpriced_value() : formatGray(hazard.peak),
		detail: (hazard, _originName, bodyName) => {
			if (hazard.unpriced) return m.travel_hazard_belt_unpriced_detail({ body: bodyName });
			const dose = lethalDoseFraction(hazard.peak);
			const span = spanFields(
				percentParts(dose / BELT_MODEL_UNCERTAINTY_FACTOR),
				percentParts(dose * BELT_MODEL_UNCERTAINTY_FACTOR)
			);
			return m.travel_hazard_belt_detail({
				body: bodyName,
				value: ltrIsolate(formatPercent(dose)),
				low: ltrIsolate(span.low),
				high: ltrIsolate(span.high)
			});
		}
	},
	dust: {
		name: m.travel_hazard_dust,
		chip: (hazard) => m.travel_hazard_dust_chip({ value: formatJoules(hazard.peak, DIGITS) }),
		// Two measures on one line. Without an isolate each, right-to-left text
		// joins the first unit and the second figure into one run. The TNT
		// equivalent is only in the detail: on this line it would push the name
		// of the row into a narrow column.
		value: (hazard) =>
			m.travel_hazard_dust_value({
				size: quantityIsolate(grainSize(hazard.dust!.radiusM)),
				energy: ltrIsolate(formatJoules(hazard.peak, DIGITS))
			}),
		detail: (hazard) => {
			const dust = hazard.dust!;
			const fields = {
				size: quantityIsolate(grainSize(dust.radiusM)),
				energy: formatJoulesWithTnt(hazard.peak, DIGITS),
				total: formatJoulesWithTnt(dust.energyJPerM2, DIGITS)
			};
			return dust.extrapolated
				? m.travel_hazard_dust_detail_extrapolated({
						...fields,
						measured: quantityIsolate(grainSize(MEASURED_GRAIN_RADIUS_M))
					})
				: m.travel_hazard_dust_detail(fields);
		}
	},
	gas: {
		name: m.travel_hazard_gas,
		// A word on the chip: the map shows it without the icon, beside the
		// cosmic ray chip, which is also in sieverts.
		chip: (hazard) => m.travel_hazard_gas_chip({ value: formatSievert(hazard.peak) }),
		value: (hazard) => formatSievert(hazard.peak),
		detail: (hazard) => {
			const value = ltrIsolate(formatSievert(hazard.rateAtPeak ?? 0));
			switch (gasReading(hazard.peak)) {
				case 'risk':
					return m.travel_hazard_gas_detail({
						value,
						risk: ltrIsolate(formatPercent(cancerRiskFraction(hazard.peak)))
					});
				case 'past-model':
					return m.travel_hazard_gas_past_model({ value });
				case 'lethal':
					return m.travel_hazard_gas_lethal({ value });
			}
		}
	}
};

/** The largest quality factor of Q(L) (ICRP 60), which Sato et al. 2009 use.
 *  A dose equivalent over it is the least absorbed dose it can be. */
const MAX_QUALITY_FACTOR = 30;

/** From this many lethal doses, a dose is many lethal doses. */
const MANY_LETHAL_DOSES = 5;

/** The last sentence of the gas row. */
export type GasReading = 'risk' | 'past-model' | 'lethal';

/**
 * The gas row goes from 0.1 Sv to 10⁹ Sv. It gives the cancer risk while the
 * linear model holds. Past it, the row says that the dose is many lethal doses
 * only where this is true at any quality factor. A lethal dose is in grays and
 * the row is in sieverts.
 */
export function gasReading(sv: number): GasReading {
	if (cancerRiskFraction(sv) < 1) return 'risk';
	return lethalDoseFraction(sv / MAX_QUALITY_FACTOR) >= MANY_LETHAL_DOSES ? 'lethal' : 'past-model';
}

/** A shield thickness, in mm, cm or m as fits it. */
function thickness(metres: number): string {
	return joinPartsNoBreak(lengthParts(metres, DIGITS));
}

/** The front reads as a shield of its own only when it is clearly thicker than
 *  the sides. */
const SEPARATE_FRONT_RATIO = 1.33;

/** The ISS dose rate, in running text. In mSv, not µSv: it is read against the
 *  cosmic-ray rate, which is in mSv. */
function issDose(): string {
	return joinPartsNoBreak({
		value: sigFigures(ISS_DOSE_SV_PER_DAY * 1e3, DIGITS),
		unit: m.symbol_millisievert()
	});
}

/** One row of the shield. The shield is not a hazard, so it has no chip. */
export interface ShieldRow {
	name: string;
	value: string;
	detail: string;
}

/** The rows of the shield under the hazards: a frontal and a side shield when
 *  the front is clearly thicker, else one shield all round at the front value. */
export function shieldRows(shield: RadiationShield): ShieldRow[] {
	const target = ltrIsolate(issDose());
	const ice = (metres: number) =>
		m.travel_hazard_shield_value({ thickness: quantityIsolate(thickness(metres)) });
	if (shield.frontIceM <= SEPARATE_FRONT_RATIO * shield.sideIceM) {
		return [
			{
				name: m.travel_hazard_shield_all(),
				value: ice(shield.frontIceM),
				detail: m.travel_hazard_shield_all_detail({ target })
			}
		];
	}
	return [
		{
			name: m.travel_hazard_shield_front(),
			value: ice(shield.frontIceM),
			detail: m.travel_hazard_shield_front_detail({
				target,
				iron: quantityIsolate(thickness(shield.frontIronM)),
				concrete: quantityIsolate(thickness(CONCRETE_CAP_M))
			})
		},
		{
			name: m.travel_hazard_shield_side(),
			value: ice(shield.sideIceM),
			detail: m.travel_hazard_shield_side_detail({ target })
		}
	];
}

export function hazardName(kind: HazardKind): string {
	return HAZARD_TEXT[kind].name();
}

/**
 * The shortest form: what fits on a row of trajectories, and on a chip beside
 * the arc. A figure where the figure is the point, a phrase where it is not.
 */
export function hazardChip(hazard: Hazard): string {
	return HAZARD_TEXT[hazard.kind].chip(hazard);
}

/** The figure that sits on the right of a detail row. */
export function hazardValue(hazard: Hazard): string {
	return HAZARD_TEXT[hazard.kind].value(hazard);
}

/** What it means for the craft, in a sentence. `originName` is read only by
 *  the conjunction, defined against the place the trip left; `bodyName` only
 *  by a belt crossing, defined against a body the trip merely passes. */
export function hazardDetail(hazard: Hazard, originName: string, bodyName = ''): string {
	return HAZARD_TEXT[hazard.kind].detail(hazard, originName, bodyName);
}

/** The extra line a craft adds to a hazard, or null when it has nothing to say. */
export function hazardCraftNote(hazard: AdjustedHazard): string | null {
	const note = hazard.craftNote;
	if (!note) return null;
	return note.kind === 'nuclear-power'
		? m.travel_hazard_craft_nuclear()
		: m.travel_hazard_craft_entry({ value: formatDv(note.ratedKms) });
}

/** The months of passes an aerobraking arrival adds, when it has any. */
export function hazardCampaign(hazard: Hazard): string | null {
	if (hazard.kind !== 'aeroassist') return null;
	const days = hazard.endJd - hazard.startJd;
	if (!(days > 1)) return null;
	return m.travel_hazard_aero_campaign({ value: formatDurationNarrow(days) });
}

/** Attach the chip text the scene shows along the path. */
export function labelHazards(hazards: readonly Hazard[]): LabelledHazard[] {
	return hazards.map((hazard) => ({ ...hazard, label: hazardChip(hazard) }));
}
