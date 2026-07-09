/**
 * Show reloading feedback for one paint, then hard-reload. A full reload is the
 * only recovery for a lost GL context or a failed boot fetch; the unloading page
 * can't measure the fresh boot, so callers pair this with an indeterminate bar.
 */
export function startPageReload(onStart: () => void): void {
	onStart();
	// Two frames so the disabled button + bar paint before the reload tears down.
	requestAnimationFrame(() => requestAnimationFrame(() => location.reload()));
}
