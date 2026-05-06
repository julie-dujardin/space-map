/**
 * Integration harness: reads a real exported `major/10` chunk and evaluates
 * Earth's position at J2000.
 *
 * Skipped pending a fresh export: the fixture in `__fixtures__/major-10.bin.gz`
 * was generated with the v6 format (separate `SCHB` magic at
 * `chebyshev/{zone}/{chunk}/data.bin.gz`); the parser now expects the v7
 * unified `SMAP` header at `position/{zone}/0/{chunk}.bin.gz` with a per-body
 * header that carries the new `object_type` byte. Re-run the export and
 * regenerate the fixture to re-enable.
 */

import { describe, it } from 'vitest';

describe.skip('chebyshev harness (real export)', () => {
	it('placeholder until v7 fixture is regenerated', () => {});
});
