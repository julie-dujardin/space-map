/** The keys that open search from anywhere on a page. */

/** Ctrl+K on a Mac is the text fields' own line editing, so ⌘K there. */
function apple(): boolean {
	return typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform);
}

export function isSearchShortcut(e: KeyboardEvent): boolean {
	if (!(apple() ? e.metaKey : e.ctrlKey) || e.altKey || e.shiftKey) return false;
	// A layout with no Latin letters still has its K key where QWERTY has it.
	return e.key.toLowerCase() === 'k' || (!/^[a-z]$/i.test(e.key) && e.code === 'KeyK');
}

/** The shortcut as a key cap shows it. */
export function searchShortcutLabel(): string {
	return apple() ? '⌘K' : 'Ctrl K';
}
