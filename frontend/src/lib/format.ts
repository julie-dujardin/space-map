/** Map URL type segment to backend ID prefix. Inverse of urlTypeFromId. */
export function urlTypeToIdPrefix(urlType: string): string {
	if (urlType === 'sb') return 'spkid';
	if (urlType === 'sat') return 'norad_satcat';
	return 'naif'; // body, probe
}

/** Derive URL type segment from a prefixed body ID. Use this for URL generation — it's always consistent with the ID. */
export function urlTypeFromId(id: string): string {
	if (id.startsWith('spkid-')) return 'sb';
	if (id.startsWith('norad_satcat-')) return 'sat';
	return 'body'; // naif-
}
