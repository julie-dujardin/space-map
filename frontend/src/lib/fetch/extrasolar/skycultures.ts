/**
 * The sky cultures of the extrasolar export
 * (`docs/export-format/extrasolar.md`, "Sky cultures"): one gzip JSON file per
 * culture, whose `token` field is the `skycultures` token of `metadata.json`.
 */

import {
	extrasolarAllowed,
	extrasolarPath,
	fetchExtrasolarJson,
	fetchExtrasolarMetadata,
	type ExtrasolarCredit
} from './files';

/** The catalogues behind a figure's line ends. */
const POSITION_CATALOGUE = /^(Gaia Data Release|Hipparcos)/;

export interface SkyCultureName {
	native?: string;
	english?: string;
}

export interface SkyCultureMember {
	id?: number;
	/** pc, in the frame of the render tree. Absent on what the tree does not draw. */
	position?: [number, number, number];
}

export interface SkyCultureFigure {
	id: string;
	kind: 'constellation' | 'asterism';
	names: SkyCultureName[];
	/** Chains of member indexes, joined in order. */
	lines: number[][];
	/** The IAU abbreviation. */
	iau?: string;
	/** Name by site language. */
	labels?: Record<string, string>;
}

export interface SkyCultureFile {
	token: string;
	key: string;
	members: SkyCultureMember[];
	figures: SkyCultureFigure[];
}

export interface SkyCultureEntry {
	key: string;
	distribution: string;
	credit: ExtrasolarCredit;
}

export interface ExtrasolarSkyCultures {
	token: string;
	/** Path pattern of a culture file, with `{key}`. */
	file: string;
	cultures: SkyCultureEntry[];
}

export interface LoadedSkyCulture {
	file: SkyCultureFile;
	/** The culture, then the catalogues that place its stars. */
	credits: ExtrasolarCredit[];
}

/** A culture and its credit, or null where the export or the host has none. */
export async function fetchSkyCulture(key: string): Promise<LoadedSkyCulture | null> {
	const metadata = await fetchExtrasolarMetadata();
	const table = metadata?.skycultures;
	const entry = table?.cultures.find((culture) => culture.key === key);
	if (!metadata || !table || !entry || !extrasolarAllowed(entry)) return null;
	const path = extrasolarPath(table.file, { key });
	const file = await fetchExtrasolarJson<SkyCultureFile>(path, table.token);
	const places = metadata.credits.filter((credit) => POSITION_CATALOGUE.test(credit.name));
	return { file, credits: [entry.credit, ...places] };
}
