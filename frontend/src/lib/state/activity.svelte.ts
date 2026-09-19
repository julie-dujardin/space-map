import { fetchActivity, type ActivityFile } from '$lib/fetch/activity';

/**
 * The live contact feed as a signal: null until it lands, then the file, and
 * re-read from the network when a reader asks after it has gone stale. A
 * failed fetch settles at null too, so a panel never waits on it.
 */
let file = $state<ActivityFile | null>(null);
let inflight: Promise<ActivityFile | null> | null = null;

export function activityFeed(): ActivityFile | null {
	const promise = fetchActivity();
	if (promise !== inflight) {
		inflight = promise;
		promise.then((result) => {
			if (inflight === promise) file = result;
		});
	}
	return file;
}
