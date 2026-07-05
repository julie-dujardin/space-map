import { DATA_BASE, getDataVersions } from '$lib/fetch/data-base';

/**
 * Redeploy detection. `?v=` tokens are query strings on stable paths, so after a
 * data deploy an old session fetches new bytes under old tokens → silent refresh
 * failures. Comparing live tokens against a fresh metadata.json catches it.
 */
async function dataVersionChanged(): Promise<boolean> {
	try {
		const res = await fetch(`${DATA_BASE}/v1/metadata.json`, { cache: 'no-store' });
		if (!res.ok) return false;
		const meta = (await res.json()) as { versions?: Record<string, string> };
		const live = getDataVersions();
		// Before metadata resolves every key trivially "differs" against no live
		// tokens — a false positive, so wait until there's something to compare.
		if (Object.keys(live).length === 0) return false;
		const next = meta.versions ?? {};
		const keys = new Set([...Object.keys(live), ...Object.keys(next)]);
		for (const k of keys) if (live[k] !== next[k]) return true;
		return false;
	} catch {
		return false;
	}
}

/**
 * Re-check the data version on tab refocus (no polling timer — the moment a
 * long-idle session comes back); invoke `onStale` once on a detected redeploy.
 * Returns a disposer.
 */
export function watchDataVersion(onStale: () => void): () => void {
	let fired = false;
	const check = async () => {
		if (fired || document.visibilityState !== 'visible') return;
		if (await dataVersionChanged()) {
			fired = true;
			onStale();
		}
	};
	document.addEventListener('visibilitychange', check);
	return () => document.removeEventListener('visibilitychange', check);
}
