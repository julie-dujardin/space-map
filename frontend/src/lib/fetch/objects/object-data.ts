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
	map_texture_available?: boolean;
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
