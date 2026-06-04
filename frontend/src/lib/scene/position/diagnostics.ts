/**
 * Warn-once-per-(channel, id) for transient position-update failures. Without
 * this the console floods at 60 fps. Probes can clear on recovery so they
 * re-warn after a future drop.
 */
type Channel = 'cheb-null' | 'probe-unavailable' | 'non-finite' | 'missing-parent';

export class PositionDiagnostics {
	private readonly seen = new Map<Channel, Set<string>>();

	private bucket(channel: Channel): Set<string> {
		let s = this.seen.get(channel);
		if (!s) this.seen.set(channel, (s = new Set()));
		return s;
	}

	warnOnce(channel: Channel, id: string, makeMessage: () => string): void {
		const s = this.bucket(channel);
		if (s.has(id)) return;
		s.add(id);
		console.warn(makeMessage());
	}

	clear(channel: Channel, id: string): void {
		this.seen.get(channel)?.delete(id);
	}
}
