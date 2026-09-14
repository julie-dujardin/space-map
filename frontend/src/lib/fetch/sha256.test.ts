import { describe, expect, it } from 'vitest';
import { sha256 } from './sha256';

const hex = (bytes: Uint8Array) => [...bytes].map((b) => b.toString(16).padStart(2, '0')).join('');

describe('sha256', () => {
	it('matches the published digests', () => {
		expect(hex(sha256(new TextEncoder().encode('')))).toBe(
			'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'
		);
		expect(hex(sha256(new TextEncoder().encode('abc')))).toBe(
			'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'
		);
	});

	it('agrees with the platform digest across block boundaries', async () => {
		for (const length of [1, 55, 56, 63, 64, 65, 119, 120, 200]) {
			const input = 'naif-499:'.repeat(64).slice(0, length);
			const expected = new Uint8Array(
				await crypto.subtle.digest('SHA-256', new TextEncoder().encode(input))
			);
			expect(hex(sha256(new TextEncoder().encode(input)))).toBe(hex(expected));
		}
	});
});
