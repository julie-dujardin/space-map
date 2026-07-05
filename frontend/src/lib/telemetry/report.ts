import { env } from '$env/dynamic/public';

/**
 * Client-error sink: console + `navigator.sendBeacon` to
 * `PUBLIC_ERROR_BEACON_URL` when set (a deploy-time toggle, e.g. a Grafana
 * ingest). Never throws.
 */
export type ClientErrorKind = 'error' | 'unhandledrejection' | 'sveltekit' | 'scene-load';

export function reportClientError(kind: ClientErrorKind, error: unknown): void {
	const err = error instanceof Error ? error : undefined;
	console.error(`[client-error:${kind}]`, error);

	const beacon = env.PUBLIC_ERROR_BEACON_URL;
	if (!beacon || typeof navigator === 'undefined' || !navigator.sendBeacon) return;
	try {
		const payload = JSON.stringify({
			kind,
			message: err?.message ?? String(error),
			stack: err?.stack,
			url: typeof location !== 'undefined' ? location.href : undefined,
			ua: navigator.userAgent,
			ts: new Date().toISOString()
		});
		navigator.sendBeacon(beacon, new Blob([payload], { type: 'application/json' }));
	} catch {
		// Reporting is best-effort — swallow so it never masks the original error.
	}
}
