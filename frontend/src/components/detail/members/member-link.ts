/**
 * What a member row shows. Where it goes is the shared link routing in
 * `focus-link`, since the three lists carry the same group / feature / body
 * split every other drawer link does.
 */
import { memberEntryKey, type NotableMemberEntry } from '$lib/fetch/objects/object-data';

/** The row's label: the locale's override, else the exported English name.
 *  Keyed the way the export writes the map — group slug, then feature, then id,
 *  with the name backstopping an entry that has no page of its own. */
export function memberDisplayName(
	entry: NotableMemberEntry,
	localizedNames?: Record<string, string>
): string {
	return localizedNames?.[memberEntryKey(entry)] ?? entry.name;
}
