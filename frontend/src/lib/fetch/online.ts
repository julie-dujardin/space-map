/** Resolves once the browser says it is online: at once where it is, or
 *  where it cannot say. */
export function untilOnline(): Promise<void> {
	if (typeof navigator === 'undefined' || navigator.onLine !== false) return Promise.resolve();
	return new Promise((resolve) =>
		window.addEventListener('online', () => resolve(), { once: true })
	);
}
