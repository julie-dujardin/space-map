/**
 * What a member row shows. Where it goes is the shared link routing in
 * `focus-link`, since the three lists carry the same group / feature / body
 * split every other drawer link does.
 */
import { memberEntryKey, type NotableMemberEntry } from '$lib/fetch/objects/object-data';
import type { LocalizedGroupData } from '$lib/fetch/groups/details';
import { formatQuantity } from '$lib/format/quantities';

/** The row's label: the locale's override, else the exported English name.
 *  Keyed the way the export writes the map — group slug, then feature, then id,
 *  with the name backstopping an entry that has no page of its own. */
export function memberDisplayName(
	entry: NotableMemberEntry,
	localizedNames?: Record<string, string>
): string {
	return localizedNames?.[memberEntryKey(entry)] ?? entry.name;
}

/** The members of the Satellite Systems page by the names of their own pages
 *  ("Jupiter system"), as an override map over every entry: their `name` is
 *  the planet's, which older clients read, and English has no localized map.
 *  An export without system names leaves the planets' names. */
export function systemMemberNames(
	members: NotableMemberEntry[] | undefined,
	localized: LocalizedGroupData | null | undefined
): Record<string, string> | undefined {
	if (!members) return localized?.notable_member_names;
	return Object.fromEntries(
		members.map((entry) => {
			const key = memberEntryKey(entry);
			const name =
				localized?.member_system_names?.[key] ??
				entry.system_name ??
				localized?.notable_member_names?.[key] ??
				entry.name;
			return [key, name];
		})
	);
}

/** The right-hand column of a member row, as text. */
export interface MemberFigures {
	diameter?: string;
	year?: string;
}

/** A diameter as the member lists write it. */
export function formatDiameterKm(km: number): string {
	return formatQuantity({ value: km, unit: 'kilometre' }, true);
}

/** The entry's diameter in km. With no diameter, twice the mean of its radii. */
export function entryDiameterKm(entry: NotableMemberEntry): number | undefined {
	if (entry.diameter_km != null) return entry.diameter_km;
	const r = entry.radii;
	return r ? (2 * (r.a + r.b + r.c)) / 3 : undefined;
}

/** The year of a YYYY-MM-DD or YYYY date. */
export function yearOf(date?: string): string | undefined {
	const year = date?.slice(0, 4);
	return year && Number.isFinite(parseInt(year, 10)) ? year : undefined;
}

/** The entry's diameter and year of first observation. */
export function entryFigures(entry: NotableMemberEntry): MemberFigures {
	const km = entryDiameterKm(entry);
	return {
		diameter: km === undefined ? undefined : formatDiameterKm(km),
		year: yearOf(entry.first_obs)
	};
}
