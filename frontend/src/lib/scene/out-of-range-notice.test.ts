import { describe, expect, it, vi } from 'vitest';
import type { Notice, NoticeSink, OutOfRangeNotice } from './notice';
import { OutOfRangeNotifier, UncoveredPass } from './out-of-range-notice';

const END = 2469807.5;
const PUCK_END = 2451544.5;

function sink() {
	const notify = vi.fn<(n: Notice) => void>();
	const dismiss = vi.fn();
	return { sink: { notify, dismiss } as NoticeSink, notify, dismiss };
}

function update(notifier: OutOfRangeNotifier, pass: UncoveredPass, focused = false): void {
	notifier.update({
		jd: END + 10,
		satellites: { kind: 'covered' },
		majorBodies: pass,
		focusedOutOfRange: focused
	});
}

const last = (notify: ReturnType<typeof sink>['notify']): OutOfRangeNotice =>
	notify.mock.calls.at(-1)![0] as OutOfRangeNotice;

describe('OutOfRangeNotifier', () => {
	it('names the bodies past their own kernels, one entry per edge, by date', () => {
		const { sink: s, notify } = sink();
		const pass = new UncoveredPass();
		pass.add('naif-999', 'Pluto', 'after', PUCK_END + 3000, false);
		pass.add('naif-715', 'Puck', 'after', PUCK_END, false);
		pass.add('naif-714', 'Cordelia', 'after', PUCK_END + 0.2, false);
		pass.add('naif-618', 'Pan', 'outside', NaN, false);
		update(new OutOfRangeNotifier(s), pass);
		const notice = last(notify);
		expect(notice.majorBodies).toBeNull();
		expect(notice.bodies).toEqual([
			{ side: 'after', jd: PUCK_END, ids: ['naif-715', 'naif-714'], names: ['Puck', 'Cordelia'] },
			{ side: 'after', jd: PUCK_END + 3000, ids: ['naif-999'], names: ['Pluto'] },
			{ side: 'outside', ids: ['naif-618'], names: ['Pan'] }
		]);
	});

	it('gives the edge of the ephemeris once it is crossed, and drops the bodies on that side', () => {
		const { sink: s, notify } = sink();
		const pass = new UncoveredPass();
		pass.add('naif-10', 'Sun', 'after', END, true);
		pass.add('naif-999', 'Pluto', 'after', PUCK_END, false);
		pass.add('naif-618', 'Pan', 'outside', NaN, false);
		update(new OutOfRangeNotifier(s), pass);
		const notice = last(notify);
		expect(notice.majorBodies).toEqual({ side: 'after', jd: END });
		expect(notice.bodies).toEqual([{ side: 'outside', ids: ['naif-618'], names: ['Pan'] }]);
	});

	it('sends nothing while the answer stays the same, and dismisses once all have data', () => {
		const { sink: s, notify, dismiss } = sink();
		const notifier = new OutOfRangeNotifier(s);
		const pass = new UncoveredPass();
		pass.add('naif-715', 'Puck', 'after', PUCK_END, false);
		update(notifier, pass);
		pass.reset();
		pass.add('naif-715', 'Puck', 'after', PUCK_END, false);
		update(notifier, pass);
		expect(notify).toHaveBeenCalledTimes(1);
		pass.add('naif-714', 'Cordelia', 'after', PUCK_END, false);
		update(notifier, pass);
		expect(notify).toHaveBeenCalledTimes(2);
		pass.reset();
		update(notifier, pass);
		expect(dismiss).toHaveBeenCalledWith('out-of-range');
	});
});
