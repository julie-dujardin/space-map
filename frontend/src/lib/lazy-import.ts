import { toast } from 'svelte-sonner';
import * as m from '$lib/paraglide/messages.js';

const RETRY_DELAY_MS = 1_000;
const TOAST_ID = 'chunk-load-failed';

/** Lazy imports that failed and have not loaded since. The toast stays while any does. */
let failing = 0;

/** Vite's preload helper never fetches a failed stylesheet again, so a retry
 *  would mount the component without its styles. */
function isStylesheetFailure(e: unknown): boolean {
	return e instanceof Error && e.message.startsWith('Unable to preload CSS');
}

async function readyToRetry(): Promise<void> {
	if (!navigator.onLine) {
		await new Promise<void>((resolve) =>
			window.addEventListener('online', () => resolve(), { once: true })
		);
	}
	await new Promise((resolve) => setTimeout(resolve, RETRY_DELAY_MS));
}

/**
 * A lazy import that tries a failed chunk download once more, when the
 * connection is up. `onFailure` runs at the first failure. Chromium keeps a
 * failed module for the life of the page, so there the retry fails too and
 * only a reload recovers.
 */
export async function importWithRetry<T>(
	load: () => Promise<T>,
	onFailure: () => void
): Promise<T> {
	try {
		return await load();
	} catch (e) {
		console.error('[lazy-import] a chunk did not load:', e);
		onFailure();
		if (isStylesheetFailure(e)) throw e;
	}
	await readyToRetry();
	try {
		return await load();
	} catch (e) {
		console.error('[lazy-import] a chunk did not load on retry:', e);
		throw e;
	}
}

/** {@link importWithRetry} that tells a failure in a toast with a reload.
 *  Null when the chunk does not load. */
export async function lazyImport<T>(load: () => Promise<T>): Promise<T | null> {
	let failed = false;
	try {
		const mod = await importWithRetry(load, () => {
			failed = true;
			failing++;
			toast.error(m.page_part_load_failed(), {
				id: TOAST_ID,
				duration: Number.POSITIVE_INFINITY,
				action: { label: m.reload(), onClick: () => location.reload() }
			});
		});
		if (failed && --failing === 0) toast.dismiss(TOAST_ID);
		return mod;
	} catch {
		return null;
	}
}
