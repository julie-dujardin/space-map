/**
 * One reader gesture, switched on and off on its own. Mapbox hangs a handler
 * like this off the map for each gesture it knows, and both maps here do the
 * same, so `map.scrollZoom.disable()` reads alike on either of them.
 */
export class GestureHandler {
	private enabled: boolean;
	private readonly apply: ((enabled: boolean) => void) | undefined;

	/** @internal `apply` carries the change to whatever reads the gesture — the
	 *  orbit controls, a DOM listener — and runs only when the answer changes. */
	constructor(enabled: boolean, apply?: (enabled: boolean) => void) {
		this.enabled = enabled;
		this.apply = apply;
	}

	enable(): void {
		this.set(true);
	}

	disable(): void {
		this.set(false);
	}

	isEnabled(): boolean {
		return this.enabled;
	}

	private set(enabled: boolean): void {
		if (this.enabled === enabled) return;
		this.enabled = enabled;
		this.apply?.(enabled);
	}
}

/** Whether a gesture starts on: what the map was told about it, else the
 *  map-wide `interactive`, which is true unless a host says otherwise. */
export function gestureStart(one: boolean | undefined, all: boolean | undefined): boolean {
	return one ?? all ?? true;
}
