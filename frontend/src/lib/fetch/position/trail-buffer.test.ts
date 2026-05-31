import { describe, it, expect } from 'vitest';
import { TrailBuffer } from './trail-buffer';

describe('TrailBuffer', () => {
	it('starts empty', () => {
		const buf = new TrailBuffer(4, 1);
		expect(buf.count).toBe(0);
		expect(buf.newestJd).toBeNaN();
	});

	it('appends up to capacity', () => {
		const buf = new TrailBuffer(3, 1);
		buf.append(1, 10, 20, 30);
		buf.append(2, 11, 21, 31);
		buf.append(3, 12, 22, 32);
		expect(buf.count).toBe(3);
		expect(buf.newestJd).toBe(3);
	});

	it('overwrites oldest when full', () => {
		const buf = new TrailBuffer(3, 1);
		buf.append(1, 1, 0, 0);
		buf.append(2, 2, 0, 0);
		buf.append(3, 3, 0, 0);
		buf.append(4, 4, 0, 0); // evicts the jd=1 sample
		expect(buf.count).toBe(3);
		expect(buf.newestJd).toBe(4);

		const out = new Float32Array(9);
		const n = buf.writeVertices(out, 0, 0, 0);
		expect(n).toBe(3);
		// Newest-first: jd=4, jd=3, jd=2
		expect(Array.from(out.slice(0, 3))).toEqual([4, 0, 0]);
		expect(Array.from(out.slice(3, 6))).toEqual([3, 0, 0]);
		expect(Array.from(out.slice(6, 9))).toEqual([2, 0, 0]);
	});

	it('writeVertices applies offset', () => {
		const buf = new TrailBuffer(2, 1);
		buf.append(1, 1, 2, 3);
		buf.append(2, 4, 5, 6);
		const out = new Float32Array(6);
		const n = buf.writeVertices(out, 100, 200, 300);
		expect(n).toBe(2);
		expect(Array.from(out.slice(0, 3))).toEqual([104, 205, 306]);
		expect(Array.from(out.slice(3, 6))).toEqual([101, 202, 303]);
	});

	it('writeVertices caps at out capacity', () => {
		const buf = new TrailBuffer(4, 1);
		buf.append(1, 1, 0, 0);
		buf.append(2, 2, 0, 0);
		buf.append(3, 3, 0, 0);
		buf.append(4, 4, 0, 0);
		// out only has room for 2 points
		const out = new Float32Array(6);
		const n = buf.writeVertices(out, 0, 0, 0);
		expect(n).toBe(2);
		expect(Array.from(out.slice(0, 3))).toEqual([4, 0, 0]);
		expect(Array.from(out.slice(3, 6))).toEqual([3, 0, 0]);
	});

	it('clear resets state', () => {
		const buf = new TrailBuffer(3, 1);
		buf.append(1, 1, 0, 0);
		buf.append(2, 2, 0, 0);
		buf.clear();
		expect(buf.count).toBe(0);
		expect(buf.newestJd).toBeNaN();
		buf.append(10, 99, 0, 0);
		expect(buf.count).toBe(1);
		expect(buf.newestJd).toBe(10);
	});

	it('readNewestPos returns the latest sample', () => {
		const buf = new TrailBuffer(3, 1);
		const out: [number, number, number] = [-1, -1, -1];
		expect(buf.readNewestPos(out)).toBe(false);
		expect(out).toEqual([-1, -1, -1]); // untouched when empty
		buf.append(1, 10, 20, 30);
		buf.append(2, 11, 21, 31);
		expect(buf.readNewestPos(out)).toBe(true);
		expect(out).toEqual([11, 21, 31]);
		buf.append(3, 12, 22, 32);
		buf.append(4, 13, 23, 33); // wraps, evicting jd=1
		expect(buf.readNewestPos(out)).toBe(true);
		expect(out).toEqual([13, 23, 33]);
	});

	it('defaults epsilonScene to Infinity (legacy uniform sampling)', () => {
		const buf = new TrailBuffer(3, 1);
		expect(buf.epsilonScene).toBe(Infinity);
		const adaptive = new TrailBuffer(3, 1, 0.25);
		expect(adaptive.epsilonScene).toBe(0.25);
	});

	it('partial fill (fewer appends than capacity)', () => {
		const buf = new TrailBuffer(5, 1);
		buf.append(1, 1, 0, 0);
		buf.append(2, 2, 0, 0);
		const out = new Float32Array(15);
		const n = buf.writeVertices(out, 0, 0, 0);
		expect(n).toBe(2);
		expect(Array.from(out.slice(0, 3))).toEqual([2, 0, 0]);
		expect(Array.from(out.slice(3, 6))).toEqual([1, 0, 0]);
	});
});
