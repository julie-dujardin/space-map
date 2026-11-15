/**
 * The page of a figure of a sky culture, built in the browser from the culture
 * file that the map draws: an index entry for each of about 5,000 figures would
 * weigh on every visit. A figure that is a constellation with an article reads
 * its text and pictures from that group's data, and its stars stay its own.
 */

import { getLocale } from '$lib/host';
import { fetchLocalizedEntry, OBJECT_BUNDLES } from '$lib/fetch/bundle-pair';
import { fetchGroupDetail, type GroupDetailData } from '$lib/fetch/groups/details';
import { figureKey, SKY_CULTURE_SLUG_PREFIX } from '$lib/fetch/groups/registry';
import type { NotableMemberEntry } from '$lib/fetch/objects/object-data';
import { extrasolarObjectId } from './ids';
import { extrasolarLookup } from './lookup';
import {
	figureChart,
	figurePlaced,
	type ChartStar,
	type FigureChart
} from '$lib/star-chart/figure';
import {
	extrasolarAllowed,
	extrasolarPermanent,
	fetchExtrasolarMetadata,
	type ExtrasolarCredit
} from './files';
import {
	cultureName,
	cultureStarName,
	fetchInternationalNames,
	fetchSkyCulture,
	labelOf,
	unmatchedName,
	type LoadedSkyCulture,
	type SkyCultureFigure,
	type SkyCultureFile
} from './skycultures';

/** A figure's page by its URL segment, or undefined. */
export function findFigure(file: SkyCultureFile, figure: string): SkyCultureFigure | undefined {
	return file.figures.find(({ slug }) => slug === figure);
}

/** The name of a figure's page: its label on the map. A figure with no name in
 *  its source goes by its segment. */
export function figurePageName(figure: SkyCultureFigure, locale: string): string {
	return labelOf(figure, locale) ?? figure.slug ?? figure.id;
}

interface FoundFigure {
	culture: LoadedSkyCulture;
	figure: SkyCultureFigure;
}

/** A figure and its culture, or null where the export or the host has none. */
async function findLoadedFigure(slug: string, segment: string): Promise<FoundFigure | null> {
	const key = slug.slice(SKY_CULTURE_SLUG_PREFIX.length);
	const culture = await fetchSkyCulture(key);
	const figure = culture?.file.key === key ? findFigure(culture.file, segment) : undefined;
	return culture && figure ? { culture, figure } : null;
}

async function loadFigure(slug: string, segment: string): Promise<FoundFigure> {
	const found = await findLoadedFigure(slug, segment);
	if (!found) throw new Error(`no figure ${segment} in ${slug}`);
	return found;
}

export async function fetchFigureName(slug: string, segment: string): Promise<string> {
	return figurePageName((await loadFigure(slug, segment)).figure, getLocale());
}

/** What a chart draws of a figure. */
export interface LoadedChart {
	chart: FigureChart;
	/** The name of a star on the chart, as its row in the member list has it.
	 *  Null for a star that readers do not know and that no culture names. */
	name: (star: ChartStar) => Promise<string | null>;
	/** The works behind the chart: the culture, the catalogues that place its
	 *  members, the international names. */
	credits: ExtrasolarCredit[];
	/** Present when the international names failed in a way that can pass. It
	 *  reads them again and gives this chart with their neighbours, or with
	 *  `more` again. */
	more?: () => Promise<LoadedChart>;
}

interface StarRow {
	member: NotableMemberEntry;
	/** It has an object entry, so readers know it. */
	known: boolean;
	/** Null for a star that only its number names. */
	name: string | null;
}

type StarNamer = (id: number, fallback: string | undefined) => Promise<StarRow>;

/**
 * The stars of a figure's page by name, for its member list and for its chart.
 * What a constellation's data holds of a star is kept. Another star takes the
 * name of its object entry in the reader's language, else of its Metadata row,
 * else `fallback`. A failed read costs the name, not the page.
 */
function starNamer(page: GroupDetailData | null, lang: string): StarNamer {
	const held = new Map(page?.global?.notable_members?.map((member) => [member.id, member]));
	const localized = page?.localized?.notable_member_names;
	return async (id, fallback) => {
		const objectId = extrasolarObjectId(id);
		const member = held.get(objectId);
		if (member) return { member, known: true, name: localized?.[objectId] ?? member.name };
		const found = await extrasolarLookup.live(id, { data: false }).catch(() => null);
		const meta = found?.kind === 'live' ? found.record.metadata : null;
		const entry = meta?.object
			? await fetchLocalizedEntry<{ name?: string }>(OBJECT_BUNDLES, objectId, lang).catch(
					() => null
				)
			: null;
		const name = entry?.name ?? meta?.name ?? fallback ?? null;
		return { member: { id: objectId, name: name ?? String(id) }, known: !!meta?.object, name };
	};
}

/** The members of a figure, in the order of its lines with the stars that have
 *  an entry first. A star on two lines comes once, and a point of the sky is
 *  no member. */
async function figureMembers(
	file: SkyCultureFile,
	figure: SkyCultureFigure,
	star: StarNamer
): Promise<NotableMemberEntry[]> {
	const names = new Map(file.names.map(({ member, names }) => [member, names]));
	const indexes = [...new Set([...figure.lines.flat(), ...(figure.group ?? [])])];
	const rows = await Promise.all(
		indexes.map(async (index): Promise<Pick<StarRow, 'member' | 'known'> | null> => {
			const member = file.members[index];
			if (member.id === undefined) {
				const name = unmatchedName(member);
				return name ? { member: { name }, known: false } : null;
			}
			return star(member.id, cultureStarName(names.get(index)));
		})
	);
	return rows
		.filter((row) => row !== null)
		.sort((a, b) => Number(b.known) - Number(a.known))
		.map(({ member }) => member);
}

/** The chart of a figure, from the files that its page holds. The
 *  international names add neighbours, so a failed read of them costs no chart.
 *  A read of them again keeps the figure as it is. */
async function loadChart(
	{ file, credits }: LoadedSkyCulture,
	figure: SkyCultureFigure,
	star: StarNamer
): Promise<LoadedChart> {
	const bare = figureChart(file, figure);
	const base = {
		name: async ({ id, given }: ChartStar) => {
			const { name, known } = await star(id, given);
			return known || given ? name : null;
		},
		credits: credits.filter((credit) => !credit.deep_sky || bare.standIns.length > 0)
	};
	const read = async (): Promise<LoadedChart> => {
		try {
			const international = await fetchInternationalNames();
			if (!international) return { ...base, chart: bare };
			const { neighbours } = figureChart(file, figure, [international.file]);
			return {
				...base,
				chart: { ...bare, neighbours },
				credits: [...base.credits, ...(international.credit ? [international.credit] : [])]
			};
		} catch (e) {
			return { ...base, chart: bare, more: extrasolarPermanent(e) ? undefined : read };
		}
	};
	return read();
}

/**
 * A figure as a group's detail bundle, so that the drawer reads it as any other
 * page. Rejects when the culture holds no such page.
 */
export async function fetchFigureDetail(
	slug: string,
	segment: string,
	lang: string = getLocale()
): Promise<GroupDetailData> {
	const { culture, figure } = await loadFigure(slug, segment);
	const { file, entry } = culture;
	const page = figure.page ? await fetchGroupDetail(figure.page, lang) : null;
	const star = starNamer(page, lang);
	const members = await figureMembers(file, figure, star);
	return {
		global: {
			...page?.global,
			slug: figureKey(slug, segment),
			type: 'sky_constellation',
			applies_to: 'star',
			member_count: members.filter(({ id }) => id).length,
			notable_members: members,
			// A culture out of the picker has no page to climb to.
			parent_group: entry.group === null ? page?.global?.parent_group : slug,
			culture_text: figure.description
				? { text: figure.description, distribution: entry.distribution, credit: entry.credit }
				: undefined,
			figure_credit: entry.credit,
			star_chart: figurePlaced(file, figure)
				? { slug, figure: segment, load: () => loadChart(culture, figure, star) }
				: undefined
		},
		localized: {
			...page?.localized,
			name: figurePageName(figure, lang),
			parent_group_name:
				entry.group === null ? page?.localized?.parent_group_name : cultureName(entry, lang)
		}
	};
}

/** Why a figure has no chart: the host serves no sky cultures, the page has
 *  not accepted the culture's non-commercial terms, or the culture has no such
 *  figure with a place in the sky. */
export type StarChartErrorReason = 'unavailable' | 'non-commercial' | 'not-found';

/** A figure with no chart here. `reason` says why. */
export class StarChartError extends Error {
	constructor(
		readonly reason: StarChartErrorReason,
		message: string
	) {
		super(`spacemap: ${message}`);
		this.name = 'StarChartError';
	}
}

/**
 * A figure's name and chart, for a chart with no page around it. Rejects with
 * a {@link StarChartError} when the figure has no chart, and as the fetch does
 * when a file does not load.
 */
export async function fetchFigureChart(
	slug: string,
	segment: string,
	lang: string = getLocale()
): Promise<{ name: string; chart: LoadedChart }> {
	const table = (await fetchExtrasolarMetadata())?.skycultures;
	if (!table) throw new StarChartError('unavailable', 'this host serves no sky cultures');
	const key = slug.startsWith(SKY_CULTURE_SLUG_PREFIX)
		? slug.slice(SKY_CULTURE_SLUG_PREFIX.length)
		: null;
	const entry = table.cultures.find((culture) => culture.key === key);
	if (!entry) throw new StarChartError('not-found', `no sky culture ${slug}`);
	if (!extrasolarAllowed(entry))
		throw new StarChartError(
			'non-commercial',
			`${slug} is for non-commercial use: set includeNonCommercial to draw it`
		);
	const found = await findLoadedFigure(slug, segment);
	if (!found || !figurePlaced(found.culture.file, found.figure))
		throw new StarChartError(
			'not-found',
			`no figure ${segment} with a place in the sky in ${slug}`
		);
	const { culture, figure } = found;
	// The page only adds the localized names of its stars.
	const page = figure.page ? await fetchGroupDetail(figure.page, lang).catch(() => null) : null;
	return {
		name: figurePageName(figure, lang),
		chart: await loadChart(culture, figure, starNamer(page, lang))
	};
}
