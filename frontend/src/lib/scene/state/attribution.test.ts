import { describe, it, expect } from 'vitest';
import { OrbitalSource } from '$lib/fetch/position/format';
import type { ContextManager } from './context-manager.svelte';
import type { PositionedBody } from '$lib/types/objects';
import { CreditsStore } from './credits.svelte';
import { creditedOrbitSources } from './attribution';

/** Just the parts the credit filter reads: what has been recorded, where the
 *  camera is, and the one parent-child link the Earth system needs. */
function fakeCtx(credits: CreditsStore, focusedSystemId: string | null): ContextManager {
	return {
		credits,
		visibility: { focusedSystemId },
		bodies: {
			isInSystem: (parentId: string, sysId: string | null) =>
				parentId === sysId || (sysId === 'naif-3' && parentId === 'naif-399')
		}
	} as unknown as ContextManager;
}

function body(id: string, parentId: string, orbitalSource: OrbitalSource): PositionedBody {
	return { data: { id, parentId, orbitalSource } } as unknown as PositionedBody;
}

const sourcesOf = (ctx: ContextManager) => creditedOrbitSources(ctx).map(({ source }) => source);

describe('creditedOrbitSources', () => {
	it('credits an unscoped source wherever the camera is', () => {
		const credits = new CreditsStore();
		credits.recordOrbitSources([body('naif-499', 'naif-4', OrbitalSource.HORIZONS)]);
		expect(sourcesOf(fakeCtx(credits, null))).toEqual([OrbitalSource.HORIZONS]);
	});

	it('holds an asteroid-moon source back until its system is focused', () => {
		const credits = new CreditsStore();
		credits.recordOrbitSources([
			body('naif-499', 'naif-4', OrbitalSource.HORIZONS),
			body('spkid-120136199', 'spkid-20136199', OrbitalSource.ASTERSAT)
		]);
		expect(sourcesOf(fakeCtx(credits, 'naif-3'))).toEqual([OrbitalSource.HORIZONS]);
		expect(sourcesOf(fakeCtx(credits, 'spkid-20136199'))).toContain(OrbitalSource.ASTERSAT);
	});

	it('credits an Earth-satellite source anywhere in the Earth system', () => {
		const credits = new CreditsStore();
		credits.recordOrbitSources([body('25544', 'naif-399', OrbitalSource.CELESTRAK)]);
		// The Moon and a lunar orbiter resolve to naif-3 too, so one case covers them.
		expect(sourcesOf(fakeCtx(credits, 'naif-3'))).toEqual([OrbitalSource.CELESTRAK]);
		expect(sourcesOf(fakeCtx(credits, 'naif-4'))).toEqual([]);
	});

	it('credits a scoped source recorded without a parent rather than dropping it', () => {
		const credits = new CreditsStore();
		credits.recordOrbitSource(OrbitalSource.ASTERSAT);
		expect(sourcesOf(fakeCtx(credits, 'naif-3'))).toEqual([OrbitalSource.ASTERSAT]);
	});
});
