import { describe, expect, it, vi } from 'vitest';
import type { ChebyshevBody } from './parse';
import type { FetchedChebyshev } from './fetch';

const { fetchChebyshev } = vi.hoisted(() => ({ fetchChebyshev: vi.fn() }));
vi.mock('$lib/fetch/position/chebyshev/fetch', () => ({ fetchChebyshev }));

import { ChebyshevStore, type ChebyshevZoneParams } from './store';
import { tdbToUtc } from '$lib/time/jd';

const START = 2305447.5; // 1600-01-01
const CHUNK = 1826.25;

/** Ten chunks. Pluto's kernel stops after the fourth; Puck's starts in the sixth. */
const params = (): Map<string, ChebyshevZoneParams> =>
	new Map([
		[
			'major',
			{
				zoom: 0,
				chunks: 10,
				chunk_days: CHUNK,
				start_jd: START,
				end_jd: START + 10 * CHUNK,
				bodies: {
					'naif-10': [[START, START + 10 * CHUNK]],
					'naif-999': [[START, START + 4 * CHUNK]],
					'naif-715': [[START + 5.5 * CHUNK, START + 10 * CHUNK]]
				}
			}
		]
	]);

function chunk(idx: number, ids: string[]): FetchedChebyshev {
	const bodies = ids.map((id) => ({ id }) as ChebyshevBody);
	return {
		startJd: START + idx * CHUNK,
		endJd: START + (idx + 1) * CHUNK,
		bodies,
		byId: new Map(bodies.map((b) => [b.id, b]))
	} as unknown as FetchedChebyshev;
}

describe('ChebyshevStore', () => {
	it('knows every body of the manifest and its edges before any chunk loads', () => {
		const store = new ChebyshevStore(params());
		expect(store.has('naif-999')).toBe(true);
		expect(store.coverage('naif-999')).toEqual([[tdbToUtc(START), tdbToUtc(START + 4 * CHUNK)]]);
		expect(store.zoneCoverage('naif-715')).toEqual({
			start: tdbToUtc(START),
			end: tdbToUtc(START + 10 * CHUNK)
		});
		expect(store.has('naif-301')).toBe(false);
		expect(store.coverage('naif-301')).toBeUndefined();
	});

	it('loads the bodies the boot chunk lacks from the chunk of theirs nearest the date', async () => {
		fetchChebyshev.mockReset();
		fetchChebyshev.mockImplementation((_zone: string, _zoom: number, idx: number) =>
			Promise.resolve(chunk(idx, idx <= 3 ? ['naif-10', 'naif-999'] : ['naif-10', 'naif-715']))
		);
		const store = new ChebyshevStore(params());
		// In the eighth chunk: Pluto's kernel ended three chunks before.
		await store.loadStrays(tdbToUtc(START + 7.5 * CHUNK));
		expect(fetchChebyshev.mock.calls.map((c) => c[2])).toEqual([3]);
		expect([...store.strayBodies()].map((s) => s.body.id)).toEqual(['naif-999']);
	});

	it('loads nothing when the boot chunk holds every body', async () => {
		fetchChebyshev.mockReset();
		const p = params().get('major')!;
		p.bodies['naif-715'] = [[START, START + 10 * CHUNK]];
		p.bodies['naif-999'] = [[START, START + 10 * CHUNK]];
		const full = new ChebyshevStore(new Map([['major', p]]));
		await full.loadStrays(tdbToUtc(START + 0.5 * CHUNK));
		expect(fetchChebyshev).not.toHaveBeenCalled();
		expect([...full.strayBodies()]).toEqual([]);
	});

	it('does not ask for a chunk no body reaches, which the writer leaves out', async () => {
		fetchChebyshev.mockReset();
		fetchChebyshev.mockImplementation((_zone: string, _zoom: number, idx: number) =>
			Promise.resolve(chunk(idx, ['naif-715']))
		);
		const p = params().get('major')!;
		p.bodies = { 'naif-715': [[START + 5.5 * CHUNK, START + 10 * CHUNK]] };
		const store = new ChebyshevStore(new Map([['major', p]]));
		await store.load(tdbToUtc(START + 1.5 * CHUNK));
		expect(fetchChebyshev).not.toHaveBeenCalled();
		await store.load(tdbToUtc(START + 5.7 * CHUNK));
		expect(fetchChebyshev.mock.calls.map((c) => c[2])).toContain(5);
	});
});
