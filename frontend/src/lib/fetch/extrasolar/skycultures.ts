/**
 * The sky cultures of the extrasolar export
 * (`docs/export-format/extrasolar.md`, "Sky cultures"): one gzip JSON file per
 * culture, whose `token` field is the `skycultures` token of `metadata.json`.
 */

import { DEFAULT_SKY_CULTURE } from '$lib/constants';
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
	pronounce?: string;
}

export interface SkyCultureMember {
	id?: number;
	/** The object as the source writes it, on a member with no ID. */
	ref?: string;
	/** pc, in the frame of the render tree. Absent on what the tree does not draw. */
	position?: [number, number, number];
	/** The source of a position's distance, where no star of the tree holds it. */
	stand_in?: string;
}

export interface SkyCultureFigure {
	id: string;
	kind: 'constellation' | 'asterism';
	names: SkyCultureName[];
	/** Chains of member indexes, joined in order. */
	lines: number[][];
	/** The IAU abbreviation, or the IAU constellation that holds the figure. */
	iau?: string;
	/** A star group with no lines. */
	group?: number[];
	/** A pointer to find stars by: no figure. */
	ray_helper?: boolean;
	/** Name by site language, where the culture's own names are not enough. */
	labels?: Record<string, string>;
	/** The slug of the figure's page. */
	page?: string;
}

/** What a star's page reads of a figure. */
export type StarFigure = Pick<SkyCultureFigure, 'names' | 'labels' | 'page'>;

export interface StarFigureShard {
	token: string;
	/** By extrasolar ID, then by culture key. */
	stars: Record<string, Record<string, StarFigure[]>>;
}

export interface StarFigures {
	cultures: SkyCultureEntry[];
	figures: Record<string, StarFigure[]>;
}

const NO_FIGURES: StarFigures = { cultures: [], figures: {} };

export interface SkyCultureFile {
	token: string;
	key: string;
	members: SkyCultureMember[];
	figures: SkyCultureFigure[];
}

export interface SkyCultureEntry {
	key: string;
	name: string;
	/** Region group of the picker; null on a culture it leaves out. */
	group: string | null;
	/** Name by site language; a language with none reads `name`. */
	labels: Record<string, string>;
	figures: number;
	distribution: string;
	credit: ExtrasolarCredit;
}

export interface ExtrasolarSkyCultures {
	token: string;
	/** Path pattern of a culture file, with `{key}`. */
	file: string;
	/** Path pattern of a shard of the figures of each star, with `{shard}`. */
	star_figures: string;
	/** A star's shard is its ID modulo this. */
	star_shards: number;
	cultures: SkyCultureEntry[];
	credits: ExtrasolarCredit[];
}

export interface LoadedSkyCulture {
	file: SkyCultureFile;
	/** The culture, then the catalogues that place its stars. */
	credits: ExtrasolarCredit[];
}

/** A site language in another script than the Latin one reads a native name
 *  in its own script; no export field gives a culture's language. */
const LOCALE_SCRIPT: Record<string, RegExp> = {
	zh: /\p{Script=Han}/u,
	ja: /[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}]/u,
	ar: /\p{Script=Arabic}/u,
	he: /\p{Script=Hebrew}/u,
	ru: /\p{Script=Cyrillic}/u
};

/** A native name the reader's script can show, else the name in the reader's
 *  language, else the English one: a translation of the English gloss never
 *  beats the name itself, and a reader of a Latin-script language cannot read
 *  most native names. Null on a figure with no name. */
export function labelOf(figure: StarFigure, locale: string): string | null {
	const names = figure.names;
	const script = LOCALE_SCRIPT[locale];
	return (
		(script && names.find(({ native }) => native && script.test(native))?.native) ||
		figure.labels?.[locale] ||
		names.find(({ english }) => english)?.english ||
		names.find(({ pronounce }) => pronounce)?.pronounce ||
		names.find(({ native }) => native)?.native ||
		null
	);
}

/** The cultures a reader may pick. */
export function pickableCultures(table: ExtrasolarSkyCultures): SkyCultureEntry[] {
	return table.cultures.filter((culture) => culture.group !== null && extrasolarAllowed(culture));
}

/** What the layer draws for a stored `key`: a key that the export or the host
 *  no longer offers reads as the default. */
export function pickedCulture(
	cultures: readonly SkyCultureEntry[],
	key: string
): SkyCultureEntry | undefined {
	return (
		cultures.find((culture) => culture.key === key) ??
		cultures.find((culture) => culture.key === DEFAULT_SKY_CULTURE)
	);
}

/** The cultures of the picker, or null where the export has none. */
export async function fetchPickableCultures(): Promise<SkyCultureEntry[] | null> {
	const table = (await fetchExtrasolarMetadata())?.skycultures;
	return table ? pickableCultures(table) : null;
}

/** The cultures a reader may pick that hold a star, and its figures by culture
 *  key. The shard holds every culture. */
export async function fetchStarFigures(id: number): Promise<StarFigures> {
	const table = (await fetchExtrasolarMetadata())?.skycultures;
	if (!table) return NO_FIGURES;
	const path = extrasolarPath(table.star_figures, { shard: id % table.star_shards });
	const shard = await fetchExtrasolarJson<StarFigureShard>(path, table.token);
	const figures = shard.stars[String(id)];
	if (!figures) return NO_FIGURES;
	return { cultures: pickableCultures(table).filter(({ key }) => key in figures), figures };
}

/** Whether a figure draws a deep-sky stand-in. A member only in `names` has no
 *  place on the map. */
function drawsDeepSky({ members, figures }: SkyCultureFile): boolean {
	const standsIn = (index: number) => !!members[index].ref && !!members[index].position;
	return figures.some(
		({ lines, group, ray_helper }) =>
			!ray_helper && (lines.flat().some(standsIn) || !!group?.some(standsIn))
	);
}

/** A culture and its credit, or null where the export or the host has none. */
export async function fetchSkyCulture(key: string): Promise<LoadedSkyCulture | null> {
	const metadata = await fetchExtrasolarMetadata();
	const table = metadata?.skycultures;
	// A constellation page can draw a culture that the picker leaves out.
	const entry = table && pickedCulture(table.cultures.filter(extrasolarAllowed), key);
	if (!metadata || !table || !entry) return null;
	const path = extrasolarPath(table.file, { key: entry.key });
	const file = await fetchExtrasolarJson<SkyCultureFile>(path, table.token);
	const places = metadata.credits.filter((credit) => POSITION_CATALOGUE.test(credit.name));
	const deepSky = drawsDeepSky(file) ? table.credits.filter((credit) => credit.deep_sky) : [];
	return { file, credits: [entry.credit, ...places, ...deepSky] };
}
