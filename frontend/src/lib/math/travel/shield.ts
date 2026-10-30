/**
 * The ice it takes to bring the radiation of a crossing between two stars down
 * to the average on the ISS.
 *
 * - The front meets the gas and, at speed, nearly all the cosmic rays, boosted.
 *   Up to about 0.45 c the cosmic rays set its thickness. Above that the gas does.
 * - The sides and back meet the cosmic rays while the craft is slow. Their share
 *   outside the front cone is largest at rest, so one thickness holds for every
 *   crossing.
 * - The front is a disc 10 m across with the crew 5 m behind its centre: a cone
 *   of 45°.
 * - Good to about ±25%.
 */

/** The ISS average dose equivalent, Sv/day: charged particles, Q(L)-based, the
 *  same quantity as the cosmic ray row. DOSTEL 2009–2016 (Berger et al. 2017),
 *  ISS-RAD 2024 (Laramore et al. 2025). */
export const ISS_DOSE_SV_PER_DAY = 0.6e-3;

/** How thick a shield has to be, in ice, and at the front also in iron. */
export interface RadiationShield {
	/** At the front, m: against the gas and the cosmic rays ahead at top speed. */
	frontIceM: number;
	/** At the front in iron, m, with {@link CONCRETE_CAP_M} of concrete behind it. */
	frontIronM: number;
	/** On the sides and back, m: against the cosmic rays while the craft is slow. */
	sideIceM: number;
}

/** Concrete behind an iron shield, m. Iron does not slow the neutrons below
 *  about 1 MeV, so they need hydrogen behind it (Cossairt, TM-1834 §6.3.5). */
export const CONCRETE_CAP_M = 0.6;

const ICE_G_CM3 = 0.917;
const IRON_G_CM3 = 7.874;

/** Water on the sides and back, g/cm². Iron makes no sense there: against
 *  cosmic rays, heavy nuclei raise the dose with depth. */
// Slaba et al. 2016 (NASA benchmark), Globus & Strout 2017, Sato 2015, Dobynde & Guo 2023, Corti et al. 2016.
const SIDE_WATER_G_CM2 = 303;

/**
 * The front, g/cm² of water and of iron, against the kinetic energy per nucleon
 * of the gas, MeV. It holds for the gas density, the cosmic ray rate past the
 * heliopause and {@link ISS_DOSE_SV_PER_DAY}. Below 70 MeV no source gives the
 * iron, so those values are less sure than the water.
 */
const FRONT_TABLE: readonly (readonly [tMeV: number, water: number, iron: number])[] = [
	// Slaba et al. 2016, Globus & Strout 2017, Agosteo et al. 2007, Stevenson et al. 1982, Hirayama 2010, Teichmann 2010, Cossairt (TM-1834), NIST PSTAR, Sato et al. 2009.
	[0.1, 308, 456],
	[0.3, 311, 461],
	[1, 315, 467],
	[2, 318, 471],
	[3.5, 326, 483],
	[5.8, 334, 499],
	[10, 346, 518],
	[15, 360, 543],
	[20, 370, 560],
	[30, 389, 591],
	[45, 411, 628],
	[70, 478, 864],
	[100, 596, 1096],
	[145, 843, 1539],
	[200, 1130, 1988],
	[250, 1311, 2253],
	[400, 1831, 2993],
	[700, 2371, 3650],
	[1000, 2677, 3968],
	[2000, 2730, 4048],
	[5000, 2833, 4200],
	[10000, 2912, 4316],
	[30000, 3053, 4526]
];

/** The front in g/cm² of water and of iron, at `tMeV` per nucleon of the gas.
 *  At rest the front is the side. Below the first point the cosmic rays from
 *  ahead grow about as the speed, which goes as √T. Past the last point the
 *  last value holds. */
function frontAt(tMeV: number): { water: number; iron: number } {
	const [first] = FRONT_TABLE;
	if (tMeV < first[0]) {
		const water = SIDE_WATER_G_CM2 + (first[1] - SIDE_WATER_G_CM2) * Math.sqrt(tMeV / first[0]);
		return { water, iron: (first[2] * water) / first[1] };
	}
	const i = Math.min(
		FRONT_TABLE.findLastIndex(([t]) => t <= tMeV),
		FRONT_TABLE.length - 2
	);
	const [t0, water0, iron0] = FRONT_TABLE[i];
	const [t1, water1, iron1] = FRONT_TABLE[i + 1];
	const at = Math.min(1, Math.log(tMeV / t0) / Math.log(t1 / t0));
	return { water: water0 + (water1 - water0) * at, iron: iron0 + (iron1 - iron0) * at };
}

/** The shield for a crossing whose top speed gives the gas `tMeV` per nucleon. */
export function radiationShield(tMeV: number): RadiationShield {
	const front = frontAt(tMeV);
	return {
		frontIceM: front.water / ICE_G_CM3 / 100,
		frontIronM: front.iron / IRON_G_CM3 / 100,
		sideIceM: SIDE_WATER_G_CM2 / ICE_G_CM3 / 100
	};
}
