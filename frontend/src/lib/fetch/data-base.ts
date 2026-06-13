import { env } from '$env/dynamic/public';

export const DATA_BASE = env.PUBLIC_DATA_URL || 'https://static.spacemap.co';

/**
 * Per-content-class cache-busting tokens from `metadata.json → versions`.
 * Populated once metadata resolves (see `fetchMetadata`); every versioned
 * fetch is downstream of that, so the map is set before any `versionedUrl`.
 */
let versions: Record<string, string> = {};

export function setDataVersions(v: Record<string, string> | undefined): void {
	versions = v ?? {};
}

/**
 * Build a data URL with its content class's cache-busting token appended as
 * `?v=`. Use for files under an immutable `Cache-Control` rule (see
 * `infrastructure/deploy/_headers`) so a content change yields a fresh URL.
 * Roots that stay on the revalidating default (metadata, systems, groups,
 * labels, credits) build straight off `DATA_BASE` instead.
 */
export function versionedUrl(path: string, cls: string): string {
	const token = versions[cls];
	if (!token) {
		// Only reachable before metadata resolves or on a legacy export with no
		// `versions`. Under the immutable header an unversioned URL risks a stale
		// cache entry, so surface it rather than fail silently.
		console.error(`versionedUrl: missing '${cls}' token for ${path}`);
		return `${DATA_BASE}${path}`;
	}
	return `${DATA_BASE}${path}?v=${token}`;
}
