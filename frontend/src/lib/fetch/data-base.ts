import { env } from '$env/dynamic/public';

export const DATA_BASE = env.PUBLIC_DATA_URL || 'https://static.spacemap.co';

/**
 * Images ship from their own origin so the frequently-redeployed data tree
 * stays small. Follows an explicit data origin when set — dev's `/data`
 * proxy serves images too — else the prod host.
 */
export const IMAGES_BASE = env.PUBLIC_DATA_URL || 'https://images.spacemap.co';

/**
 * Per-content-class cache-busting tokens from `metadata.json → versions`.
 * Populated once metadata resolves (see `fetchMetadata`); every versioned
 * fetch is downstream of that, so the map is set before any `versionedUrl`.
 */
let versions: Record<string, string> = {};

export function setDataVersions(v: Record<string, string> | undefined): void {
	versions = v ?? {};
}

/** The live per-class version tokens. The version-skew watcher compares these
 *  against a freshly-fetched metadata.json to detect a redeploy mid-session. */
export function getDataVersions(): Record<string, string> {
	return versions;
}

/**
 * Data URL with its content class's cache-busting token appended as `?v=`,
 * for files under an immutable `Cache-Control` rule. Roots on the
 * revalidating default build straight off `DATA_BASE` instead.
 */
export function versionedUrl(path: string, cls: string): string {
	return buildVersionedUrl(DATA_BASE, path, cls);
}

/** Like `versionedUrl` but against the images origin (always the `images`
 *  content class). */
export function versionedImageUrl(path: string): string {
	return buildVersionedUrl(IMAGES_BASE, path, 'images');
}

function buildVersionedUrl(base: string, path: string, cls: string): string {
	const token = versions[cls];
	if (!token) {
		// Before metadata resolves, or on a legacy export: an unversioned URL
		// risks a stale cache entry under the immutable header, so surface it.
		console.error(`versionedUrl: missing '${cls}' token for ${path}`);
		return `${base}${path}`;
	}
	return `${base}${path}?v=${token}`;
}
