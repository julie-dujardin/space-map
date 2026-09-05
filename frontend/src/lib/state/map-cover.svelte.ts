import { untrack } from 'svelte';

/**
 * What fullscreen UI sits over the map. While anything holds a claim the
 * scene stops drawing behind it. Claims count rather than toggle: a picker
 * opens over a sheet that already covers.
 */
export class MapCover {
	#claims = $state(0);

	get covered(): boolean {
		return this.#claims > 0;
	}

	/** Take a claim; the returned function releases it. */
	claim(): () => void {
		this.#claims++;
		let held = true;
		return () => {
			if (!held) return;
			held = false;
			this.#claims--;
		};
	}

	/** Hold a claim while `open` reads true — always, when omitted — for the
	 *  calling component's lifetime. */
	hold(open: () => boolean = () => true): void {
		$effect(() => {
			if (!open()) return;
			// The increment reads the count; tracked, that read would loop the effect.
			return untrack(() => this.claim());
		});
	}
}
