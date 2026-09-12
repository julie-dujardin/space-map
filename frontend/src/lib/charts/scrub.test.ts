import { describe, it, expect, vi } from 'vitest';
import { createScrub, DRAG_SLOP } from './scrub';

function pointer(pointerType: string, clientX: number, clientY: number): PointerEvent {
	return { pointerType, clientX, clientY } as PointerEvent;
}

describe('createScrub', () => {
	it('ignores mouse pointers, which keep their own hover handlers', () => {
		const onScrub = vi.fn();
		const onEnd = vi.fn();
		const scrub = createScrub({ onScrub, onEnd });

		scrub.onpointerdown(pointer('mouse', 0, 0));
		scrub.onpointermove(pointer('mouse', 100, 100));
		scrub.onpointerup();

		expect(onScrub).not.toHaveBeenCalled();
		expect(onEnd).not.toHaveBeenCalled();
	});

	it('leaves a tap alone and previews once the drag passes the slop', () => {
		const onScrub = vi.fn();
		const onEnd = vi.fn();
		const scrub = createScrub({ onScrub, onEnd });

		scrub.onpointerdown(pointer('touch', 10, 10));
		scrub.onpointermove(pointer('touch', 10 + DRAG_SLOP - 1, 10));
		expect(onScrub).not.toHaveBeenCalled();

		scrub.onpointermove(pointer('touch', 10 + DRAG_SLOP, 10));
		expect(onScrub).toHaveBeenCalledWith(10 + DRAG_SLOP, 10);

		// Past the slop every move previews, however small.
		scrub.onpointermove(pointer('touch', 11, 10));
		expect(onScrub).toHaveBeenCalledTimes(2);

		scrub.onpointerup();
		expect(onEnd).toHaveBeenCalledTimes(1);
	});

	it('ends a tap without clearing anything the tap is about to act on', () => {
		const onEnd = vi.fn();
		const scrub = createScrub({ onScrub: vi.fn(), onEnd });

		scrub.onpointerdown(pointer('touch', 10, 10));
		scrub.onpointerup();

		expect(onEnd).not.toHaveBeenCalled();
	});

	it('needs a fresh press after a cancel or a leave', () => {
		const onScrub = vi.fn();
		const scrub = createScrub({ onScrub, onEnd: vi.fn() });

		scrub.onpointerdown(pointer('touch', 10, 10));
		scrub.onpointercancel();
		scrub.onpointermove(pointer('touch', 200, 200));

		expect(onScrub).not.toHaveBeenCalled();
	});
});
