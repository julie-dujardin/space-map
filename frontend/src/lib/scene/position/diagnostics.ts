/**
 * Warn-once sets for transient position-update failures. Without these the
 * console floods at 60 fps. Each channel surfaces one message per body id;
 * the probe channel allows clearing when the body recovers.
 */
export class PositionDiagnostics {
	private readonly chebNull = new Set<string>();
	private readonly probeUnavailable = new Set<string>();
	private readonly nonFinite = new Set<string>();

	warnChebNull(id: string, makeMessage: () => string): void {
		if (this.chebNull.has(id)) return;
		this.chebNull.add(id);
		console.warn(makeMessage());
	}

	warnProbeUnavailable(id: string, makeMessage: () => string): void {
		if (this.probeUnavailable.has(id)) return;
		this.probeUnavailable.add(id);
		console.warn(makeMessage());
	}

	clearProbeUnavailable(id: string): void {
		this.probeUnavailable.delete(id);
	}

	warnNonFinite(id: string, makeMessage: () => string): void {
		if (this.nonFinite.has(id)) return;
		this.nonFinite.add(id);
		console.warn(makeMessage());
	}
}
