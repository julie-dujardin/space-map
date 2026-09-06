import { host } from '$lib/host';

/** Root of the data export, as the host configured it. */
export function dataBase(): string {
	return host().dataUrl;
}

/** Root of the image export; its own origin in production so the
 *  frequently-redeployed data tree stays small. */
export function imagesBase(): string {
	return host().imagesUrl;
}

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
 * revalidating default build straight off `dataBase()` instead.
 */
export function versionedUrl(path: string, cls: string): string {
	return buildVersionedUrl(dataBase(), path, cls);
}

/** Like `versionedUrl` but against the images origin (always the `images`
 *  content class). */
export function versionedImageUrl(path: string): string {
	return buildVersionedUrl(imagesBase(), path, 'images');
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
