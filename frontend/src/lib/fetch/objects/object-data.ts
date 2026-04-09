import { getLocale } from '$lib/paraglide/runtime.js';

// --- Global object data (non-localized) ---

export interface QuantityWithUnit {
	value: number;
	unit: string;
}

export interface CurrencyQuantity {
	value: number;
	currency: string;
}

export interface GlobalObjectData {
	id: string;
	type: string;
	name?: string;
	map_texture_available?: boolean;
	sbdb_primary_designation?: string;
	provisional_designation?: string;
	nasa_science_url?: string;
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
		e: number;
		i: number;
		om: number;
		w: number;
		scale: string;
		parent_naif_id: number;
		source: string;
		// Keplerian elements (standard orbits)
		a?: number;
		ma?: number;
		n?: number;
		// Parabolic elements (e=1 comets)
		q?: number;
		tp?: number;
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
		mass?: QuantityWithUnit;
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
		ad?: number;
		prefix?: string;
		M1?: number;
		M2?: number;
		K1?: number;
		K2?: number;
		PC?: number;
		first_obs?: string;
		last_obs?: string;
		data_arc?: number;
		n_obs_used?: number;
		condition_code?: number;
	};
	wikidata?: {
		discovery_date?: string[];
		launch_date?: string;
		image?: string[];
		mass?: QuantityWithUnit;
		radius?: QuantityWithUnit;
		density?: QuantityWithUnit;
		surface_gravity?: QuantityWithUnit;
		absolute_magnitude?: number;
		apparent_magnitude?: number;
		temperature?: QuantityWithUnit;
		min_temperature?: QuantityWithUnit;
		max_temperature?: QuantityWithUnit;
		population?: number;
		website?: string[];
		blog?: string[];
		logo_image?: string[];
		capital_cost?: CurrencyQuantity;
		length?: QuantityWithUnit;
		width?: QuantityWithUnit;
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
	instance_of?: EntityRef[];
	discoverers?: EntityRef[];
	named_after?: EntityRef[];
	discovery_site?: EntityRef[];
	minor_planet_group?: EntityRef[];
	spectral_type?: EntityRef[];
	asteroid_family?: EntityRef;
	operator?: EntityRef[];
	manufacturer?: EntityRef[];
	launch_vehicle?: EntityRef;
	launch_site?: EntityRef[];
	developer?: EntityRef[];
	funder?: EntityRef[];
	country_of_origin?: EntityRef[];
	launch_contractor?: EntityRef[];
	part_of?: EntityRef[];
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
	const res = await fetch(url);
	if (!res.ok) {
		if (res.status === 404) return null;
		throw new Error(`fetchJson: ${url} returned ${res.status} ${res.statusText}`);
	}
	const ds = new DecompressionStream('gzip');
	return new Response(res.body!.pipeThrough(ds)).json() as Promise<T>;
}

export async function fetchObjectDetail(
	fileId: string,
	objectFileFlag = 1,
	lang = getLocale()
): Promise<ObjectDetailData> {
	const key = `${fileId}:${lang}:${objectFileFlag}`;
	const cached = cache.get(key);
	if (cached) return cached;

	let localizedPromise: Promise<LocalizedObjectData | null>;
	if (objectFileFlag === 0) {
		localizedPromise = Promise.resolve(null);
	} else if (objectFileFlag === 2) {
		localizedPromise = fetchJson<LocalizedObjectData>(`/data/v1/objects/en/${fileId}.json.gz`);
	} else {
		localizedPromise = fetchJson<LocalizedObjectData>(`/data/v1/objects/${lang}/${fileId}.json.gz`);
	}

	const [global, localized] = await Promise.all([
		fetchJson<GlobalObjectData>(`/data/v1/objects/__global__/${fileId}.json.gz`),
		localizedPromise
	]);

	const result: ObjectDetailData = { global, localized };
	cache.set(key, result);
	return result;
}
