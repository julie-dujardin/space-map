import { afterEach, describe, expect, it, vi } from 'vitest';
import { attachCanvasForwarders } from './forward';

class FakePointer extends Event {
	clientX: number;
	clientY: number;
	button: number;
	constructor(type: string, init: { clientX?: number; clientY?: number; button?: number } = {}) {
		super(type);
		this.clientX = init.clientX ?? 0;
		this.clientY = init.clientY ?? 0;
		this.button = init.button ?? 0;
	}
}

function setup(forwardTap: boolean) {
	const win = new EventTarget();
	vi.stubGlobal('window', win);
	vi.stubGlobal('PointerEvent', FakePointer);
	const label = new EventTarget() as HTMLElement;
	const canvas = new EventTarget() as HTMLCanvasElement;
	const seen: string[] = [];
	for (const type of ['pointerdown', 'pointermove', 'pointerup']) {
		canvas.addEventListener(type, () => seen.push(type));
	}
	attachCanvasForwarders(label, canvas, forwardTap);
	return { win, label, seen };
}

afterEach(() => vi.unstubAllGlobals());

describe('attachCanvasForwarders', () => {
	it('keeps a tap on a label that has a click of its own', () => {
		const { win, label, seen } = setup(false);
		label.dispatchEvent(new FakePointer('pointerdown'));
		win.dispatchEvent(new FakePointer('pointerup'));
		expect(seen).toEqual([]);
	});

	it('passes a tap on as the pair the canvas picks from', () => {
		const { win, label, seen } = setup(true);
		label.dispatchEvent(new FakePointer('pointerdown'));
		win.dispatchEvent(new FakePointer('pointerup'));
		expect(seen).toEqual(['pointerdown', 'pointerup']);
	});

	it('passes on no button but the main one', () => {
		const { win, label, seen } = setup(true);
		label.dispatchEvent(new FakePointer('pointerdown', { button: 2 }));
		win.dispatchEvent(new FakePointer('pointerup', { button: 2 }));
		expect(seen).toEqual([]);
	});

	it('hands a drag over once, with no tap after it', () => {
		const { win, label, seen } = setup(true);
		label.dispatchEvent(new FakePointer('pointerdown'));
		win.dispatchEvent(new FakePointer('pointermove', { clientX: 20 }));
		win.dispatchEvent(new FakePointer('pointerup', { clientX: 20 }));
		expect(seen).toEqual(['pointerdown', 'pointermove']);
	});
});
