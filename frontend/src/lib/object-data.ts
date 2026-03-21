import { getLocale } from '$lib/paraglide/runtime.js';

// --- Global object data (non-localized) ---

export interface QuantityWithUnit {
	value: number;
	unit: string;
}

export interface GlobalObjectData {
	id: string;
	type: string;
	name?: string;
	provisional_designation?: string;
	cross_refs?: {
		wikidata_qid?: string;
		horizons_naif_id?: number;
		sbdb_spkid?: number;
		sbdb_mcp_designation?: string;
		celestrak_norad_cat_id?: number;
		celestrak_cospar_id?: string;
	};
	orbit?: {
		epoch_jd: number;
		a: number;
		e: number;
		i: number;
		om: number;
		w: number;
		ma: number;
		n: number;
		scale: string;
		parent_naif_id: number;
		source: string;
	};
	physical?: {
		mass_kg?: number;
		radius_km?: number;
	};
	sbdb?: {
		neo?: boolean;
		pha?: boolean;
		class?: string;
		sats?: number;
		diameter?: number;
		extent?: string;
		albedo?: number;
		rot_per?: number;
		GM?: number;
		H?: number;
		G?: number;
		spec_B?: string;
		spec_T?: string;
		BV?: number;
		UB?: number;
		IR?: number;
		moid?: number;
		moid_jup?: number;
		t_jup?: number;
		per_y?: number;
		q?: number;
		ad?: number;
		prefix?: string;
		M1?: number;
		M2?: number;
		K1?: number;
		K2?: number;
		PC?: number;
		first_obs?: string;
	};
	wikidata?: {
		discovery_date?: string;
		launch_date?: string;
		image?: string;
		mass?: QuantityWithUnit;
		radius?: QuantityWithUnit;
		density?: QuantityWithUnit;
		surface_gravity?: QuantityWithUnit;
		absolute_magnitude?: number | QuantityWithUnit;
		apparent_magnitude?: number | QuantityWithUnit;
		temperature?: QuantityWithUnit;
		min_temperature?: QuantityWithUnit;
		max_temperature?: QuantityWithUnit;
		website?: string;
	};
}

// --- Localized object data ---

export interface EntityRef {
	name: string;
	wikipedia?: string;
}

export interface LocalizedObjectData {
	name?: string;
	description?: string;
	aliases?: string[];
	discoverers?: EntityRef[];
	named_after?: EntityRef;
	discovery_site?: EntityRef;
	minor_planet_group?: EntityRef;
	spectral_type?: EntityRef;
	asteroid_family?: EntityRef;
	operator?: EntityRef;
	manufacturer?: EntityRef;
	launch_vehicle?: EntityRef;
	launch_site?: EntityRef;
	wikipedia?: {
		extract?: string;
		description?: string;
		thumbnail?: string;
		image?: string;
		url?: string;
	};
}

// --- Fetching ---

export interface ObjectDetailData {
	global: GlobalObjectData | null;
	localized: LocalizedObjectData | null;
}

const cache = new Map<string, ObjectDetailData>();

async function fetchJson<T>(url: string): Promise<T | null> {
	try {
		const res = await fetch(url);
		if (!res.ok) return null;
		return (await res.json()) as T;
	} catch {
		return null;
	}
}

export async function fetchObjectDetail(
	fileId: string,
	lang = getLocale()
): Promise<ObjectDetailData> {
	const key = `${fileId}:${lang}`;
	const cached = cache.get(key);
	if (cached) return cached;

	const [global, localized] = await Promise.all([
		fetchJson<GlobalObjectData>(`/data/v1/objects/__global__/${fileId}.json`),
		fetchJson<LocalizedObjectData>(`/data/v1/objects/${lang}/${fileId}.json`)
	]);

	const result: ObjectDetailData = { global, localized };
	cache.set(key, result);
	return result;
}
