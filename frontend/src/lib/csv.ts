import Papa from 'papaparse';
import { type HorizonsBody, type SmallBody, type Satellite, BodyType } from './types';

async function fetchCSV<T extends Record<string, unknown>>(path: string): Promise<T[]> {
	const res = await fetch(path);
	const text = await res.text();
	const { data } = Papa.parse<T>(text, { header: true, dynamicTyping: true, skipEmptyLines: true });
	return data;
}

export async function fetchHorizons(): Promise<HorizonsBody[]> {
	const rows = await fetchCSV<Record<string, unknown>>('/data/horizons/bodies.csv');
	return rows.map((r) => ({
		name: r['name'] ? String(r['name']) : null,
		designation: r['designation'] ? String(r['designation']) : null,
		naifId: Number(r['naif_id']),
		type: String(r['type']) as BodyType,
		parentNaifId: Number(r['parent_naif_id'] ?? 0),
		a: Number(r['A']),
		e: Number(r['EC']),
		i: Number(r['IN']),
		om: Number(r['OM']),
		w: Number(r['W']),
		ma: Number(r['MA'])
	}));
}

export async function fetchSmallBodies(): Promise<SmallBody[]> {
	const rows = await fetchCSV<Record<string, unknown>>('/data/sbdb/small-bodies.csv');
	return rows.map((r) => ({
		fullName: String(r['full_name']).trim(),
		name: r['name'] ? String(r['name']) : null,
		a: Number(r['a']),
		e: Number(r['e']),
		i: Number(r['i']),
		om: Number(r['om']),
		w: Number(r['w']),
		ma: Number(r['ma'])
	}));
}

export async function fetchSatellites(): Promise<Satellite[]> {
	const rows = await fetchCSV<Record<string, unknown>>('/data/celes-trak/gp-active.csv');
	return rows.map((r) => ({
		objectName: String(r['OBJECT_NAME']),
		meanMotion: Number(r['MEAN_MOTION']),
		eccentricity: Number(r['ECCENTRICITY']),
		inclination: Number(r['INCLINATION']),
		raan: Number(r['RA_OF_ASC_NODE']),
		argOfPericenter: Number(r['ARG_OF_PERICENTER']),
		meanAnomaly: Number(r['MEAN_ANOMALY'])
	}));
}
