import { describe, expect, it } from 'vitest';
import { opaqueWebp } from './webp-opaque';

function chunk(name: string, payload: number[]): number[] {
	const size = payload.length;
	const bytes = [...name].map((c) => c.charCodeAt(0));
	bytes.push(size & 255, (size >> 8) & 255, (size >> 16) & 255, size >>> 24, ...payload);
	if (size & 1) bytes.push(0);
	return bytes;
}

function riff(chunks: number[][]): ArrayBuffer {
	const body = [...'WEBP'].map((c) => c.charCodeAt(0)).concat(...chunks);
	const size = body.length;
	const head = [...'RIFF'].map((c) => c.charCodeAt(0));
	head.push(size & 255, (size >> 8) & 255, (size >> 16) & 255, size >>> 24);
	return new Uint8Array([...head, ...body]).buffer;
}

describe('opaqueWebp', () => {
	it('keeps only the colour chunk of an extended file', () => {
		const vp8 = chunk('VP8 ', [1, 2, 3]);
		const file = riff([chunk('VP8X', Array(10).fill(16)), chunk('ALPH', [9, 9, 9, 9]), vp8]);
		expect([...new Uint8Array(opaqueWebp(file))]).toEqual([...new Uint8Array(riff([vp8]))]);
	});

	it('leaves a simple file as it is', () => {
		const file = riff([chunk('VP8 ', [1, 2])]);
		expect(opaqueWebp(file)).toBe(file);
	});

	it('leaves a lossless file as it is', () => {
		const file = riff([chunk('VP8X', Array(10).fill(16)), chunk('VP8L', [1, 2, 3, 4])]);
		expect(opaqueWebp(file)).toBe(file);
	});
});
