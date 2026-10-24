/** Keeps switch-driven visibility changes independent of camera speed. */
export const SWITCH_FADE_MS = 500;

export class SwitchFade {
	private progress: number;
	private target: number;
	private started: boolean;

	/** An omitted initial state snaps the first update to avoid a startup fade. */
	constructor(on?: boolean) {
		this.started = on !== undefined;
		this.progress = this.target = on ? 1 : 0;
	}

	step(on: boolean, dtMs: number): void {
		this.target = on ? 1 : 0;
		if (!this.started) {
			this.started = true;
			this.progress = this.target;
			return;
		}
		const delta = dtMs / SWITCH_FADE_MS;
		this.progress =
			this.target === 1 ? Math.min(this.progress + delta, 1) : Math.max(this.progress - delta, 0);
	}

	get share(): number {
		const p = this.progress;
		return p * p * (3 - 2 * p);
	}

	get fading(): boolean {
		return this.progress !== this.target;
	}
}
