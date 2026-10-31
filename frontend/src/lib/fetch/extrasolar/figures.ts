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
	cultureName,
	fetchSkyCulture,
	labelOf,
	type LoadedSkyCulture,
	type SkyCultureFigure,
	type SkyCultureFile,
	type SkyCultureName
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

async function loadFigure(
	slug: string,
	segment: string
): Promise<{ culture: LoadedSkyCulture; figure: SkyCultureFigure }> {
	const key = slug.slice(SKY_CULTURE_SLUG_PREFIX.length);
	const culture = await fetchSkyCulture(key);
	const figure = culture?.file.key === key ? findFigure(culture.file, segment) : undefined;
	if (!culture || !figure) throw new Error(`no figure ${segment} in ${slug}`);
	return { culture, figure };
}

export async function fetchFigureName(slug: string, segment: string): Promise<string> {
	return figurePageName((await loadFigure(slug, segment)).figure, getLocale());
}

interface MemberRow {
	member: NotableMemberEntry;
	/** It has an object entry, so readers know it. */
	known: boolean;
}

/** The name a star takes from the culture that draws it. */
function cultureStarName(names: SkyCultureName[] | undefined): string | undefined {
	const name = names?.[0];
	return name?.english ?? name?.native ?? name?.pronounce;
}

/** A star as a member row: the name of its object entry in the reader's
 *  language, else of its Metadata row. A failed read costs the name, not the page. */
async function starMember(
	id: number,
	lang: string,
	fallback: string | undefined
): Promise<MemberRow> {
	const objectId = extrasolarObjectId(id);
	const found = await extrasolarLookup.live(id, { data: false }).catch(() => null);
	const meta = found?.kind === 'live' ? found.record.metadata : null;
	const entry = meta?.object
		? await fetchLocalizedEntry<{ name?: string }>(OBJECT_BUNDLES, objectId, lang).catch(() => null)
		: null;
	return {
		member: { id: objectId, name: entry?.name ?? meta?.name ?? fallback ?? String(id) },
		known: !!meta?.object
	};
}

/** The members of a figure, in the order of its lines with the stars that have
 *  an entry first. A star on two lines comes once, and a point of the sky is
 *  no member. What a constellation's data already holds of a star is kept. */
async function figureMembers(
	file: SkyCultureFile,
	figure: SkyCultureFigure,
	page: GroupDetailData | null,
	lang: string
): Promise<NotableMemberEntry[]> {
	const held = new Map(page?.global?.notable_members?.map((member) => [member.id, member]));
	const names = new Map(file.names.map(({ member, names }) => [member, names]));
	const indexes = [...new Set([...figure.lines.flat(), ...(figure.group ?? [])])];
	const rows = await Promise.all(
		indexes.map(async (index): Promise<MemberRow | null> => {
			const { id, designation, ref } = file.members[index];
			if (id === undefined) {
				const name = designation ?? ref;
				return name ? { member: { name }, known: false } : null;
			}
			const member = held.get(extrasolarObjectId(id));
			if (member) return { member, known: true };
			return starMember(id, lang, cultureStarName(names.get(index)));
		})
	);
	return rows
		.filter((row) => row !== null)
		.sort((a, b) => Number(b.known) - Number(a.known))
		.map(({ member }) => member);
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
	const members = await figureMembers(file, figure, page, lang);
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
			figure_credit: entry.credit
		},
		localized: {
			...page?.localized,
			name: figurePageName(figure, lang),
			parent_group_name:
				entry.group === null ? page?.localized?.parent_group_name : cultureName(entry, lang)
		}
	};
}
