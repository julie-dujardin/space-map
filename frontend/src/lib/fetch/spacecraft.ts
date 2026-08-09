/**
 * The vehicle catalogue, fetched once from `/data/v1/spacecraft.json`.
 *
 * Built by the pipeline from cited constants (data/src/space_map_data/
 * constants/spacecraft/), replacing the invented table the travel panel used
 * to be driven by. Every figure arrives with the source key behind it, so the
 * panel can show a citation next to a number rather than a number alone.
 *
 * A failed fetch leaves the catalogue empty, which the panel reads as "no
 * vehicle filter" — the routes still solve.
 *
 * Names come from a second, per-locale file rather than from the catalogue
 * itself: a name is the only part of a vehicle that differs per reader, and
 * twelve locales of them would cost more than the physics does. The two are
 * fetched together, and a missing name bundle leaves the picker on its English
 * fallbacks rather than failing the load.
 */

import type { DepartureMode, Vehicle } from '$lib/math/travel';
import { getLocale } from '$lib/paraglide/runtime.js';
import { DATA_BASE } from './data-base';
import { fetchWithTimeout } from './fetch-timeout';

interface MeasuredEntry {
	value: number;
	source: string;
}

interface VehicleEntry {
	id: string;
	kind: Vehicle['kind'];
	propulsion: string;
	status: Vehicle['status'];
	qid?: string;
	name?: string;
	variant?: string[];
	departs_from?: DepartureMode[];
	power?: Vehicle['power'];
	dry_mass_kg?: MeasuredEntry;
	propellant_mass_kg?: MeasuredEntry;
	isp_s?: MeasuredEntry;
	thrust_n?: MeasuredEntry;
	delta_v_kms?: number;
	c3_curve?: {
		points: [number, number][];
		source: string;
		truncated: boolean;
		cross_check?: string;
	};
	crew?: MeasuredEntry;
	/** Not emitted yet; the panel checks the hold only once it is. */
	payload_capacity_kg?: MeasuredEntry;
	endurance_days?: MeasuredEntry;
	max_entry_speed_kms?: MeasuredEntry;
	capabilities?: string[];
	capability_source?: string;
	accel_m_s2?: MeasuredEntry;
	unlimited_dv?: boolean;
	cost?: { usd_millions: number; year: number; kind: string; source: string };
	object_ids?: string[];
	group_slug?: string;
}

export interface SourceCitation {
	title: string;
	url: string;
	note: string;
}

interface SpacecraftFile {
	vehicles: VehicleEntry[];
	sources: Record<string, SourceCitation>;
}

/** One vehicle's name in the locale that was fetched, plus Wikidata's one-liner. */
export interface VehicleNaming {
	name: string;
	description?: string;
}

const vehicles: Vehicle[] = [];
const citations = new Map<string, SourceCitation>();
const naming = new Map<string, VehicleNaming>();
let loadPromise: Promise<void> | null = null;

function toVehicle(entry: VehicleEntry): Vehicle {
	return {
		id: entry.id,
		kind: entry.kind,
		// The pipeline spells it with an underscore because it is a Python
		// identifier there; everything on this side is kebab.
		propulsion: (entry.propulsion === 'solar_sail'
			? 'solar-sail'
			: entry.propulsion) as Vehicle['propulsion'],
		status: entry.status,
		qid: entry.qid,
		name: entry.name,
		variant: entry.variant,
		departsFrom: entry.departs_from,
		power: entry.power,
		dryMassKg: entry.dry_mass_kg,
		propellantMassKg: entry.propellant_mass_kg,
		ispS: entry.isp_s,
		thrustN: entry.thrust_n,
		dvKms: entry.delta_v_kms,
		c3Curve: entry.c3_curve && {
			points: entry.c3_curve.points,
			source: entry.c3_curve.source,
			truncated: entry.c3_curve.truncated,
			crossCheck: entry.c3_curve.cross_check
		},
		crew: entry.crew,
		payloadCapacityKg: entry.payload_capacity_kg,
		enduranceDays: entry.endurance_days,
		maxEntrySpeedKms: entry.max_entry_speed_kms,
		capabilities: entry.capabilities,
		accelMs2: entry.accel_m_s2,
		unlimitedDv: entry.unlimited_dv,
		cost: entry.cost && {
			usdMillions: entry.cost.usd_millions,
			year: entry.cost.year,
			kind: entry.cost.kind,
			source: entry.cost.source
		},
		objectIds: entry.object_ids,
		groupSlug: entry.group_slug
	};
}

async function loadCatalogue(): Promise<void> {
	const r = await fetchWithTimeout(`${DATA_BASE}/v1/spacecraft.json`);
	if (!r.ok) {
		console.warn(`spacecraft: fetch failed (${r.status}) — travel panel has no vehicles`);
		return;
	}
	const raw = (await r.json()) as SpacecraftFile;
	for (const [key, citation] of Object.entries(raw.sources)) citations.set(key, citation);
	vehicles.push(...raw.vehicles.map(toVehicle));
}

async function loadNames(lang: string): Promise<void> {
	const r = await fetchWithTimeout(`${DATA_BASE}/v1/spacecraft/${lang}.json`);
	if (!r.ok) {
		// Not fatal: `vehicleName` falls back to the catalogue's English name.
		console.warn(`spacecraft: no ${lang} name bundle (${r.status}) — falling back to English`);
		return;
	}
	const raw = (await r.json()) as Record<string, VehicleNaming>;
	for (const [id, entry] of Object.entries(raw)) naming.set(id, entry);
}

export function loadSpacecraft(): Promise<void> {
	if (loadPromise) return loadPromise;
	// In parallel, and the names are allowed to fail on their own: a picker
	// listing every vehicle by slug still beats one listing none.
	const p = Promise.all([loadCatalogue(), loadNames(getLocale())]).then(() => undefined);
	loadPromise = p;
	return p;
}

/** Every vehicle, in catalogue order (launchers, then real craft, then fiction). */
export function allVehicles(): readonly Vehicle[] {
	return vehicles;
}

export function vehicleById(id: string | null): Vehicle | null {
	if (!id) return null;
	return vehicles.find((v) => v.id === id) ?? null;
}

/** Localized name + Wikidata one-liner, or null for the ships with no item. */
export function vehicleNaming(id: string): VehicleNaming | null {
	return naming.get(id) ?? null;
}

/** The work behind a `source` key on any figure, for the citation line. */
export function sourceCitation(key: string | undefined): SourceCitation | null {
	return key ? (citations.get(key) ?? null) : null;
}
