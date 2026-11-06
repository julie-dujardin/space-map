import { describe, expect, it, vi } from 'vitest';
import { ImpressionNotifier } from './impression-notice';

/** The notice follows the condition and its body, and is sent once per change. */

describe('ImpressionNotifier', () => {
	it('notifies once per body while in view and dismisses once after', () => {
		const sink = { notify: vi.fn(), dismiss: vi.fn() };
		const notifier = new ImpressionNotifier(sink);
		notifier.update(null);
		notifier.update('x-1-b-1');
		notifier.update('x-1-b-1');
		notifier.update('x-1-b-2');
		notifier.update(null);
		notifier.update(null);
		expect(sink.notify.mock.calls).toEqual([
			[{ topic: 'artist-impression', id: 'x-1-b-1' }],
			[{ topic: 'artist-impression', id: 'x-1-b-2' }]
		]);
		expect(sink.dismiss).toHaveBeenCalledTimes(1);
		expect(sink.dismiss).toHaveBeenCalledWith('artist-impression');
	});
});
