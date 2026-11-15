import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fitFrame } from './frame';
import { LayeredSky } from './layered-sky';
import type { Pixels, SkySource } from './sky';

const frame = () => fitFrame([[1, 0, 0]], { width: 10, height: 10 });
const FRAME = frame();

function picture(value: number): Pixels {
	return { data: new Uint8ClampedArray([value, 0, 0, 255]), width: 1, height: 1 };
}

/** A source whose paint is answered by the test. */
function source(
	answer: () => Promise<Pixels | null>
): SkySource & { paints: number; changed: () => void } {
	const listeners = new Set<() => void>();
	const made = {
		paints: 0,
		paint: () => {
			made.paints++;
			return answer();
		},
		onChange: (listener: () => void) => {
			listeners.add(listener);
			return () => listeners.delete(listener);
		},
		changed: () => listeners.forEach((listener) => listener())
	};
	return made;
}

/** A source whose paints wait for the test, in the order asked. */
function slow(): SkySource & { paints: number; arrive: ((pixels: Pixels) => void)[] } {
	const arrive: ((pixels: Pixels) => void)[] = [];
	return Object.assign(
		source(() => new Promise<Pixels>((resolve) => arrive.push(resolve))),
		{ arrive }
	);
}

describe('LayeredSky', () => {
	beforeEach(() => {
		vi.useFakeTimers();
		vi.spyOn(console, 'warn').mockImplementation(() => {});
	});
	afterEach(() => {
		vi.useRealTimers();
		vi.restoreAllMocks();
	});

	it('paints the fine sky when it is in time', async () => {
		const sky = new LayeredSky(async () => source(async () => picture(1)));
		sky.setCoarse(source(async () => picture(2)));
		expect((await sky.paint(FRAME, 1, 1))?.data[0]).toBe(1);
	});

	it('paints the coarse sky where there is no fine one', async () => {
		const sky = new LayeredSky(async () => null);
		sky.setCoarse(source(async () => picture(2)));
		expect((await sky.paint(FRAME, 1, 1))?.data[0]).toBe(2);
	});

	it('paints the coarse sky for a slow fine one, then gives the fine picture it has', async () => {
		const fine = slow();
		const sky = new LayeredSky(async () => fine);
		sky.setCoarse(source(async () => picture(2)));
		const changed = vi.fn();
		sky.watch(FRAME, changed);
		const first = sky.paint(FRAME, 1, 1);
		await vi.advanceTimersByTimeAsync(300);
		expect((await first)?.data[0]).toBe(2);
		expect(changed).not.toHaveBeenCalled();
		const late = picture(1);
		fine.arrive[0](late);
		await vi.advanceTimersByTimeAsync(0);
		expect(changed).toHaveBeenCalledTimes(1);
		expect(await sky.paint(FRAME, 1, 1)).toBe(late);
		expect(fine.paints).toBe(1);
	});

	it('waits for the fine sky on a frame that has shown it', async () => {
		const fine = slow();
		const sky = new LayeredSky(async () => fine);
		const coarse = source(async () => picture(2));
		sky.setCoarse(coarse);
		const first = sky.paint(FRAME, 1, 1);
		await vi.advanceTimersByTimeAsync(0);
		fine.arrive[0](picture(1));
		await first;
		const second = sky.paint(FRAME, 1, 1);
		await vi.advanceTimersByTimeAsync(1000);
		fine.arrive[1](picture(3));
		expect((await second)?.data[0]).toBe(3);
		expect(coarse.paints).toBe(0);
	});

	it('tells only the chart whose fine picture is in', async () => {
		const fine = slow();
		const sky = new LayeredSky(async () => fine);
		sky.setCoarse(source(async () => picture(2)));
		const [hero, tile] = [frame(), frame()];
		const [heroTold, tileTold] = [vi.fn(), vi.fn()];
		sky.watch(hero, heroTold);
		sky.watch(tile, tileTold);
		const paints = [sky.paint(hero, 1, 1), sky.paint(tile, 1, 1)];
		await vi.advanceTimersByTimeAsync(300);
		await Promise.all(paints);
		fine.arrive[0](picture(1));
		await vi.advanceTimersByTimeAsync(0);
		expect(heroTold).toHaveBeenCalledTimes(1);
		expect(tileTold).not.toHaveBeenCalled();
		fine.arrive[1](picture(1));
		await vi.advanceTimersByTimeAsync(0);
		expect(heroTold).toHaveBeenCalledTimes(1);
		expect(tileTold).toHaveBeenCalledTimes(1);
	});

	it('waits for the fine sky while there is no coarse one', async () => {
		const fine = slow();
		const sky = new LayeredSky(async () => fine);
		const paint = sky.paint(FRAME, 1, 1);
		await vi.advanceTimersByTimeAsync(1000);
		fine.arrive[0](picture(1));
		expect((await paint)?.data[0]).toBe(1);
	});

	it('waits for the fine sky while the coarse source has no picture', async () => {
		const fine = slow();
		const sky = new LayeredSky(async () => fine);
		const coarse = source(async () => null);
		sky.setCoarse(coarse);
		const changed = vi.fn();
		sky.watch(FRAME, changed);
		let painted = false;
		const paint = sky.paint(FRAME, 1, 1).then((pixels) => {
			painted = true;
			return pixels;
		});
		await vi.advanceTimersByTimeAsync(1000);
		expect(painted).toBe(false);
		// A coarse picture now does not end the download of the fine one.
		coarse.changed();
		expect(changed).not.toHaveBeenCalled();
		fine.arrive[0](picture(1));
		expect((await paint)?.data[0]).toBe(1);
		expect(changed).not.toHaveBeenCalled();
	});

	it('counts the paints that one outage fails as one failure, and asks again later', async () => {
		let up = false;
		const fine = source(async () => {
			if (!up) throw new Error('HTTP 503');
			return picture(1);
		});
		const sky = new LayeredSky(async () => fine);
		sky.setCoarse(source(async () => picture(2)));
		const [hero, tile] = [frame(), frame()];
		const [heroTold, tileTold] = [vi.fn(), vi.fn()];
		sky.watch(hero, heroTold);
		sky.watch(tile, tileTold);
		const both = await Promise.all([sky.paint(hero, 1, 1), sky.paint(tile, 1, 1)]);
		expect(both.map((pixels) => pixels?.data[0])).toEqual([2, 2]);
		// The fine source rests: no paint asks it.
		expect((await sky.paint(hero, 1, 1))?.data[0]).toBe(2);
		expect(fine.paints).toBe(2);
		// One failure waits 2 s, give or take a quarter. Two would wait 4 s.
		up = true;
		await vi.advanceTimersByTimeAsync(2600);
		expect(heroTold).toHaveBeenCalledTimes(1);
		expect(tileTold).toHaveBeenCalledTimes(1);
		expect((await sky.paint(hero, 1, 1))?.data[0]).toBe(1);
	});

	it('opens the fine source again after it fails to open', async () => {
		let opens = 0;
		const sky = new LayeredSky(async () => {
			if (opens++ === 0) throw new Error('HTTP 503');
			return source(async () => picture(1));
		});
		sky.setCoarse(source(async () => picture(2)));
		const changed = vi.fn();
		sky.watch(FRAME, changed);
		expect((await sky.paint(FRAME, 1, 1))?.data[0]).toBe(2);
		expect(console.warn).toHaveBeenCalledTimes(1);
		await vi.advanceTimersByTimeAsync(2600);
		expect(changed).toHaveBeenCalledTimes(1);
		expect((await sky.paint(FRAME, 1, 1))?.data[0]).toBe(1);
		expect(opens).toBe(2);
	});

	it('does not count an aborted paint as a failure, and paints nothing for it', async () => {
		const stop = new AbortController();
		const fine = source(async () => {
			throw new DOMException('gone', 'AbortError');
		});
		const coarse = source(async () => picture(2));
		const sky = new LayeredSky(async () => fine);
		sky.setCoarse(coarse);
		stop.abort();
		for (let i = 0; i < 3; i++) expect(await sky.paint(FRAME, 1, 1, stop.signal)).toBeNull();
		expect(fine.paints).toBe(3);
		expect(coarse.paints).toBe(0);
	});

	it('passes a new coarse sky on only to a chart that shows it', async () => {
		const sky = new LayeredSky(async () => source(async () => picture(1)));
		const changed = vi.fn();
		sky.watch(FRAME, changed);
		await sky.paint(FRAME, 1, 1);
		sky.setCoarse(source(async () => picture(2)));
		expect(changed).not.toHaveBeenCalled();
		const bare = new LayeredSky(async () => null);
		bare.watch(FRAME, changed);
		await bare.paint(FRAME, 1, 1);
		const cube = source(async () => picture(2));
		bare.setCoarse(cube);
		expect(changed).toHaveBeenCalledTimes(1);
		cube.changed();
		expect(changed).toHaveBeenCalledTimes(2);
	});
});
