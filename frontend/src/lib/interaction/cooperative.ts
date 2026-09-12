/**
 * The compromise a map makes when it sits in a page the reader is scrolling
 * past: the wheel scrolls the page unless a modifier is held, and one finger
 * drags the page rather than the map. Two fingers, or the modifier, still move
 * the map. A hint says so whenever the plain gesture is tried.
 */

import { host } from '$lib/host';
import './cooperative.css';

/** How long the hint stays up after the last blocked gesture. */
const HINT_MS = 1400;

export class CooperativeGestures {
	private enabled: boolean;
	private readonly element = document.createElement('div');
	private timer: ReturnType<typeof setTimeout> | undefined;

	constructor(parent: HTMLElement, enabled: boolean) {
		this.enabled = enabled;
		this.element.className = 'sm-cooperative-hint';
		this.element.setAttribute('aria-hidden', 'true');
		parent.append(this.element);
	}

	isEnabled(): boolean {
		return this.enabled;
	}

	setEnabled(enabled: boolean): void {
		this.enabled = enabled;
		if (!enabled) this.hide();
	}

	/** Whether this wheel event is the map's to zoom on. A Mac reader holds ⌘,
	 *  everyone else ctrl — the same keys Mapbox asks for. */
	allowsWheel(event: WheelEvent): boolean {
		if (!this.enabled || event.ctrlKey || event.metaKey) return true;
		const { cooperative_wheel, cooperative_wheel_mac } = host().messages;
		this.show(isApple() ? cooperative_wheel_mac() : cooperative_wheel());
		return false;
	}

	/** Whether a touch drag of `fingers` fingers is the map's to follow. */
	allowsTouchDrag(fingers: number): boolean {
		if (!this.enabled || fingers > 1) return true;
		this.show(host().messages.cooperative_touch());
		return false;
	}

	dispose(): void {
		clearTimeout(this.timer);
		this.element.remove();
	}

	private show(text: string): void {
		this.element.textContent = text;
		this.element.classList.add('sm-cooperative-hint--shown');
		clearTimeout(this.timer);
		this.timer = setTimeout(() => this.hide(), HINT_MS);
	}

	private hide(): void {
		clearTimeout(this.timer);
		this.element.classList.remove('sm-cooperative-hint--shown');
	}
}

/** Apple keyboards put the modifier on ⌘, so the hint has to name it. */
function isApple(): boolean {
	return /Mac|iPhone|iPad|iPod/.test(navigator.platform || navigator.userAgent);
}
