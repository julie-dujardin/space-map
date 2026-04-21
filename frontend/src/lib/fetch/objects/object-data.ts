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

export interface ObjectImage {
	file: string;
	source_url: string;
	kind: 'photo' | 'logo';
	license: string;
	license_url?: string;
	artist?: string;
}

/** Texture attribution block — mirrors `texture_attribution()` in export/systems.py. */
export interface TextureAttribution {
	source: string;
	organisation: string;
	type: string;
	attribution?: string;
	description?: string;
}

export interface GlobalObjectData {
	id: string;
	type: string;
	name?: string;
	map_texture_available?: boolean;
	/** Only present when `map_texture_available` — mirrors `texture` in systems/{bary}.json. */
	texture?: TextureAttribution;
	images?: ObjectImage[];
	sbdb_primary_designation?: string;
	provisional_designation?: string;
	nasa_science_url?: string;
	cross_refs?: {
		wikidata_qid?: string;
		naif_id?: number;
		spkid?: number;
		mpc_designation?: string;
		norad_cat_id?: number;
		cospar_id?: string;
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
		// SGP4 init fields (CelesTrak-sourced earth sats only)
		bstar?: number;
		mean_motion_dot?: number;
		mean_motion_ddot?: number;
		element_set_no?: number;
		rev_at_epoch?: number;
	};
	orientation?: {
		pole_ra_0: number;
		pole_ra_1: number;
		pole_dec_0: number;
		pole_dec_1: number;
		w0: number;
		w1: number;
		w2: number;
	};
	nut_prec?: {
		ra: number[];
		dec: number[];
		pm: number[];
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
		capital_cost?: CurrencyQuantity;
		length?: QuantityWithUnit;
		width?: QuantityWithUnit;
	};
	celestrak?: {
		object_type?: string;
		ops_status?: string;
		data_status?: string;
		launch_date?: string;
		decay_date?: string;
		period?: number; // minutes
		apogee?: number; // km
		perigee?: number; // km
		rcs?: number; // m²
		orbit_center?: string;
		orbit_center_docked_to?: number;
		launch_site_code?: string;
		owner?: string;
		constellation_slug?: string;
		categories?: string[];
		country_codes?: string[];
	};
}

// --- Localized object data ---

export interface EntityRef {
	name: string;
	short_name?: string;
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
	operators?: EntityRef[];
	constellation?: EntityRef;
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
