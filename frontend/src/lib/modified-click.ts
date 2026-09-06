/** A non-primary / modified click (new tab, etc.) — leave it to the browser. */
export function isModifiedClick(e: MouseEvent): boolean {
	return e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey;
}
