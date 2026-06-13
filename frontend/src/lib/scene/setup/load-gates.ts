/**
 * Cross-module load-ordering gates. Large low-priority downloads (the full-res
 * skybox) await these so they never contend with the critical path for
 * bandwidth on bandwidth-bound connections.
 */
let resolveEagerMinors: () => void;

/** Resolves when the eager minor-body wave has finished ingesting. */
export const eagerMinorsDone = new Promise<void>((resolve) => {
	resolveEagerMinors = resolve;
});

export function markEagerMinorsDone(): void {
	resolveEagerMinors();
}
