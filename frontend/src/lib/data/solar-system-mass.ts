import {
	CAT_PLANETS,
	CAT_MOONS,
	CAT_DWARF_PLANETS,
	CLASS_SLUG_PREFIX
} from '$lib/fetch/groups/registry';
import * as m from '$lib/paraglide/messages.js';

// Solar-system mass inventory: Menichella (2026), Table 3 (Earth masses; lo/hi
// are the 16th/84th percentiles). Literature estimates, not in the body DB.
// https://arxiv.org/abs/2603.17561
export interface MassReservoir {
	key: string;
	label: () => string;
	central: number;
	lo: number;
	hi: number;
	color: string;
	/** Group slug the row links to. Reservoirs may share a zone (class-TNO holds
	 *  the classical belt, scattered disc and detached objects alike). */
	zone: string;
}

const CLASS_MBA = `${CLASS_SLUG_PREFIX}MBA`; // main-belt asteroids
const CLASS_TJN = `${CLASS_SLUG_PREFIX}TJN`; // Jupiter Trojans
const CLASS_TNO = `${CLASS_SLUG_PREFIX}TNO`; // trans-Neptunian objects

// Ordered outward from the Sun; colours grouped by kind (rocky, giant, small
// body, moon, trans-Neptunian, Oort).
export const MASS_RESERVOIRS: MassReservoir[] = [
	{
		key: 'terrestrial',
		label: m.mass_reservoir_terrestrial,
		central: 2.07,
		lo: 2.069,
		hi: 2.071,
		color: '#c1440e',
		zone: CAT_PLANETS
	},
	{
		key: 'main_belt',
		label: m.mass_reservoir_main_belt,
		central: 4.0e-4,
		lo: 3.2e-4,
		hi: 4.8e-4,
		color: '#b8995f',
		zone: CLASS_MBA
	},
	{
		key: 'trojans',
		label: m.mass_reservoir_trojans,
		central: 4.4e-5,
		lo: 2.2e-5,
		hi: 6.6e-5,
		color: '#cbb487',
		zone: CLASS_TJN
	},
	{
		key: 'giant',
		label: m.mass_reservoir_giant,
		central: 444.6,
		lo: 444.59,
		hi: 444.61,
		color: '#d4a66a',
		zone: CAT_PLANETS
	},
	{
		key: 'major_moons',
		label: m.mass_reservoir_major_moons,
		central: 0.104,
		lo: 0.1039,
		hi: 0.1041,
		color: '#5fa39a',
		zone: CAT_MOONS
	},
	{
		key: 'midsized_moons',
		label: m.mass_reservoir_midsized_moons,
		central: 0.004,
		lo: 0.0038,
		hi: 0.0042,
		color: '#6fae7a',
		zone: CAT_MOONS
	},
	{
		key: 'small_sats',
		label: m.mass_reservoir_small_sats,
		central: 5e-6,
		lo: 3e-6,
		hi: 7e-6,
		color: '#86b58c',
		zone: CAT_MOONS
	},
	{
		key: 'classical_kbo',
		label: m.mass_reservoir_classical_kbo,
		central: 0.02,
		lo: 0.014,
		hi: 0.026,
		color: '#5b9bd6',
		zone: CLASS_TNO
	},
	{
		key: 'dwarf',
		label: m.mass_reservoir_dwarf,
		central: 0.0027,
		lo: 0.0024,
		hi: 0.003,
		color: '#c2a378',
		zone: CAT_DWARF_PLANETS
	},
	{
		key: 'scattered',
		label: m.mass_reservoir_scattered,
		central: 0.05,
		lo: 0.017,
		hi: 0.147,
		color: '#4f86c6',
		zone: CLASS_TNO
	},
	{
		key: 'detached',
		label: m.mass_reservoir_detached,
		central: 0.005,
		lo: 0.001,
		hi: 0.025,
		color: '#7fb0e0',
		zone: CLASS_TNO
	},
	{
		key: 'oort_inner',
		label: m.mass_reservoir_oort_inner,
		central: 6.89,
		lo: 0.99,
		hi: 47.8,
		color: '#9b8cd6',
		zone: CLASS_TNO
	},
	{
		key: 'oort_outer',
		label: m.mass_reservoir_oort_outer,
		central: 3.0,
		lo: 0.6,
		hi: 14.9,
		color: '#b0a3e0',
		zone: CLASS_TNO
	}
];

// M_sun / M_earth, for the linear bar.
export const SUN_MASS_EARTHS = 332946;
export const SUN_COLOR = '#ffdd44';

/** One Earth mass (kg), to convert the figures for the unit ladder. */
export const EARTH_MASS_KG = 5.97237e24;
