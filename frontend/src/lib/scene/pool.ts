/**
 * Slot `idx` of a grow-on-demand pool, built on first use and reused after.
 * `make` must be a module-level function: an inline arrow would allocate on
 * every call, which defeats the purpose in per-frame code.
 */
export function poolSlot<T>(pool: T[], idx: number, make: () => T): T {
	let slot = pool[idx];
	if (!slot) {
		slot = make();
		pool[idx] = slot;
	}
	return slot;
}
