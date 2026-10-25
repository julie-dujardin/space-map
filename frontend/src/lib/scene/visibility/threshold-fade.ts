import { SwitchFade, WITHIN_SYSTEM_SWITCH_FADE_MS } from './switch-fade';

interface FadeEntry {
	fade: SwitchFade;
	frame: number;
}

/** Keeps visibility threshold changes independent of camera speed. */
export class VisibilityThresholdFades {
	private readonly halos = new Map<string, FadeEntry>();
	private readonly labels = new Map<string, FadeEntry>();
	private readonly orbits = new Map<string, FadeEntry>();
	private frame = 0;
	private dtMs = 0;

	beginFrame(dtMs: number): void {
		this.frame++;
		this.dtMs = dtMs;
		this.prune(this.halos);
		this.prune(this.labels);
		this.prune(this.orbits);
	}

	haloShare(id: string, shown: boolean): number {
		return this.share(this.halos, id, shown);
	}

	labelShare(id: string, shown: boolean): number {
		return this.share(this.labels, id, shown);
	}

	orbitShare(id: string, shown: boolean): number {
		return this.share(this.orbits, id, shown);
	}

	get fading(): boolean {
		return this.anyFading(this.halos) || this.anyFading(this.labels) || this.anyFading(this.orbits);
	}

	private share(entries: Map<string, FadeEntry>, id: string, shown: boolean): number {
		let entry = entries.get(id);
		if (!entry) {
			entry = {
				fade: new SwitchFade(shown, WITHIN_SYSTEM_SWITCH_FADE_MS),
				frame: this.frame
			};
			entries.set(id, entry);
		} else if (entry.frame !== this.frame) {
			entry.frame = this.frame;
			entry.fade.step(shown, this.dtMs);
		}
		return entry.fade.share;
	}

	private anyFading(entries: Map<string, FadeEntry>): boolean {
		for (const entry of entries.values()) {
			if (entry.frame === this.frame && entry.fade.fading) return true;
		}
		return false;
	}

	private prune(entries: Map<string, FadeEntry>): void {
		for (const [id, entry] of entries) {
			if (entry.frame < this.frame - 1) entries.delete(id);
		}
	}
}
