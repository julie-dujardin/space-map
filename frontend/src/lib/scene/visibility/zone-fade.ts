/** Cross-fades the solar view and the active satellite system. */

import { SwitchFade } from './switch-fade';

export interface SystemFade {
	id: string;
	fade: SwitchFade;
}

export class ZoneFades {
	private main = new SwitchFade(true);
	/** An array keeps per-body reads cheap. */
	readonly systems: SystemFade[] = [];
	private stepped = false;

	/** The first step snaps to avoid a startup fade. */
	step(activeSystemId: string | null, dtMs: number): void {
		if (!this.stepped) {
			this.stepped = true;
			this.main = new SwitchFade(activeSystemId === null);
			if (activeSystemId !== null) {
				this.systems.push({ id: activeSystemId, fade: new SwitchFade(true) });
			}
			return;
		}
		this.main.step(activeSystemId === null, dtMs);
		if (activeSystemId !== null && !this.systems.some((s) => s.id === activeSystemId)) {
			this.systems.push({ id: activeSystemId, fade: new SwitchFade(false) });
		}
		for (let i = this.systems.length - 1; i >= 0; i--) {
			const { id, fade } = this.systems[i];
			fade.step(id === activeSystemId, dtMs);
			if (fade.share === 0 && !fade.fading) this.systems.splice(i, 1);
		}
	}

	get mainShare(): number {
		return this.main.share;
	}

	get fading(): boolean {
		return this.main.fading || this.systems.some((s) => s.fade.fading);
	}
}
