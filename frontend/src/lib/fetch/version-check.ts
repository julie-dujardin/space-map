import { dataBase, getDataVersions } from '$lib/fetch/data-base';

/**
 * Redeploy detection. `?v=` tokens are query strings on stable paths, so after a
 * data deploy an old session fetches new bytes under old tokens → silent refresh
 * failures. Comparing live tokens against a fresh metadata.json catches it.
 */
async function dataVersionChanged(): Promise<boolean> {
	try {
		const res = await fetch(`${dataBase()}/v1/metadata.json`, { cache: 'no-store' });
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

/** How often a visible tab re-checks: a tab left in the foreground never fires
 *  `visibilitychange`, so it would otherwise miss a deploy entirely. */
const POLL_MS = 5 * 60_000;

/**
 * Re-check the data version on tab refocus, on a back/forward-cache restore,
 * and every few minutes while the tab is visible; invoke `onStale` once on a
 * detected redeploy. Returns a disposer.
 */
export function watchDataVersion(onStale: () => void): () => void {
	let fired = false;
	let checking = false;
	const check = async () => {
		if (fired || checking || document.visibilityState !== 'visible') return;
		checking = true;
		try {
			if (await dataVersionChanged()) {
				fired = true;
				onStale();
			}
		} finally {
			checking = false;
		}
	};
	const onPageShow = (e: PageTransitionEvent) => {
		if (e.persisted) void check();
	};
	const timer = setInterval(check, POLL_MS);
	document.addEventListener('visibilitychange', check);
	window.addEventListener('pageshow', onPageShow);
	return () => {
		clearInterval(timer);
		document.removeEventListener('visibilitychange', check);
		window.removeEventListener('pageshow', onPageShow);
	};
}
