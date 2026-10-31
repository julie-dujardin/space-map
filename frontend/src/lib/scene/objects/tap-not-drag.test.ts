import { describe, expect, it, vi } from 'vitest';
import { onLinkTap } from './tap-not-drag';

function link(): { el: HTMLAnchorElement; press: (x: number, click?: object) => Event } {
	const target = new EventTarget();
	const press = (x: number, click: object = {}): Event => {
		target.dispatchEvent(Object.assign(new Event('pointerdown'), { clientX: 0, clientY: 0 }));
		const event = Object.assign(new Event('click', { cancelable: true }), {
			clientX: x,
			clientY: 0,
			button: 0,
			...click
		});
		target.dispatchEvent(event);
		return event;
	};
	return { el: target as HTMLAnchorElement, press };
}

describe('onLinkTap', () => {
	it('opens in the session on a tap', () => {
		const { el, press } = link();
		const handler = vi.fn();
		onLinkTap(el, handler);
		expect(press(2).defaultPrevented).toBe(true);
		expect(handler).toHaveBeenCalledOnce();
	});

	it('leaves a modified click to the browser', () => {
		const { el, press } = link();
		const handler = vi.fn();
		onLinkTap(el, handler);
		expect(press(0, { ctrlKey: true }).defaultPrevented).toBe(false);
		expect(handler).not.toHaveBeenCalled();
	});

	it('neither opens nor follows the link after a drag', () => {
		const { el, press } = link();
		const handler = vi.fn();
		onLinkTap(el, handler);
		expect(press(40).defaultPrevented).toBe(true);
		expect(handler).not.toHaveBeenCalled();
	});
});
