import { describe, it, expect } from 'vitest';
import { OrbitalSource, type OrbitArchive } from '$lib/fetch/position/format';
import type { ContextManager } from './context-manager.svelte';
import type { PositionedBody } from '$lib/types/objects';
import { CreditsStore } from './credits.svelte';
import {
	attributionChips,
	creditedOrbitArchives,
	focusedModelCredit,
	scopedCredits
} from './attribution';

/** Just the parts the credit filter reads: what has been recorded, where the
 *  camera is, and the one parent-child link the Earth system needs. */
function fakeCtx(
	credits: CreditsStore,
	systemInView: string | null,
	visibility: {
		systemDrawn?: boolean;
		focusedBodyId?: string;
		focusedAtFullSize?: boolean;
		planetSystemInView?: string;
	} = {}
): ContextManager {
	return {
		credits,
		visibility: { systemInView, systemDrawn: true, ...visibility },
		bodies: {
			isInSystem: (parentId: string, sysId: string | null) =>
				parentId === sysId || (sysId === 'naif-3' && parentId === 'naif-399')
		}
	} as unknown as ContextManager;
}

function body(id: string, parentId: string, orbitalSource: OrbitalSource): PositionedBody {
	return { data: { id, parentId, orbitalSource } } as unknown as PositionedBody;
}

function probe(id: string, orbitArchive?: OrbitArchive, parentId = 'naif-10'): PositionedBody {
	return {
		data: { id, parentId, orbitalSource: OrbitalSource.SPICE_PROBE, orbitArchive }
	} as unknown as PositionedBody;
}

describe('creditedOrbitArchives', () => {
	it('credits an unscoped source wherever the camera is', () => {
		const credits = new CreditsStore();
		credits.recordOrbitSources([body('naif-499', 'naif-4', OrbitalSource.HORIZONS)]);
		expect(creditedOrbitArchives(fakeCtx(credits, null))).toEqual(['horizons']);
	});

	it('holds an asteroid-moon source back until its system is focused', () => {
		const credits = new CreditsStore();
		credits.recordOrbitSources([
			body('naif-499', 'naif-4', OrbitalSource.HORIZONS),
			body('spkid-120136199', 'spkid-20136199', OrbitalSource.ASTERSAT)
		]);
		expect(creditedOrbitArchives(fakeCtx(credits, 'naif-3'))).toEqual(['horizons']);
		expect(creditedOrbitArchives(fakeCtx(credits, 'spkid-20136199'))).toContain('nsdb');
	});

	it('credits an Earth-satellite source anywhere in the Earth system', () => {
		const credits = new CreditsStore();
		credits.recordOrbitSources([body('25544', 'naif-399', OrbitalSource.CELESTRAK)]);
		// The Moon and a lunar orbiter resolve to naif-3 too, so one case covers them.
		expect(creditedOrbitArchives(fakeCtx(credits, 'naif-3'))).toEqual(['celestrak']);
		expect(creditedOrbitArchives(fakeCtx(credits, 'naif-4'))).toEqual([]);
	});

	it('credits a scoped source recorded without a parent rather than dropping it', () => {
		const credits = new CreditsStore();
		credits.recordOrbitSource(OrbitalSource.ASTERSAT);
		expect(creditedOrbitArchives(fakeCtx(credits, 'naif-3'))).toEqual(['nsdb']);
	});

	it('lists an archive once when two sources share it', () => {
		const credits = new CreditsStore();
		credits.recordOrbitSources([
			body('spkid-20000433', 'naif-10', OrbitalSource.SBDB),
			body('spkid-120000243', 'spkid-20000243', OrbitalSource.SBDB_MOON)
		]);
		expect(creditedOrbitArchives(fakeCtx(credits, 'spkid-20000243'))).toEqual(['sbdb']);
	});

	it('credits each probe to the archive that tracked it', () => {
		const credits = new CreditsStore();
		credits.recordOrbitSources([
			probe('probe-1', 'jaxa-darts'),
			probe('probe-2', 'esa'),
			probe('probe-3', 'esa')
		]);
		expect(creditedOrbitArchives(fakeCtx(credits, null))).toEqual(['esa', 'jaxa-darts']);
	});

	it('credits a probe in orbit only while its system is in view', () => {
		const credits = new CreditsStore();
		credits.recordOrbitSources([probe('probe-1', 'clpds', 'naif-399')]);
		expect(creditedOrbitArchives(fakeCtx(credits, 'naif-3'))).toEqual(['clpds']);
		expect(creditedOrbitArchives(fakeCtx(credits, 'naif-4'))).toEqual([]);
		expect(creditedOrbitArchives(fakeCtx(credits, null))).toEqual([]);
	});

	it('credits a probe around the Sun only with no system in view', () => {
		const credits = new CreditsStore();
		credits.recordOrbitSources([probe('probe-1', 'esa')]);
		expect(creditedOrbitArchives(fakeCtx(credits, null))).toEqual(['esa']);
		expect(creditedOrbitArchives(fakeCtx(credits, 'naif-5'))).toEqual([]);
	});

	it('scopes an archive once, whichever source fed it', () => {
		const credits = new CreditsStore();
		credits.recordOrbitSources([
			body('25544', 'naif-399', OrbitalSource.SPACETRACK),
			probe('probe-1', 'spacetrack', 'naif-4')
		]);
		expect(creditedOrbitArchives(fakeCtx(credits, 'naif-3'))).toEqual(['spacetrack']);
		expect(creditedOrbitArchives(fakeCtx(credits, 'naif-4'))).toEqual(['spacetrack']);
		expect(creditedOrbitArchives(fakeCtx(credits, 'naif-5'))).toEqual([]);
	});

	it('credits nobody once the solar system no longer draws', () => {
		const credits = new CreditsStore();
		credits.recordOrbitSources([body('naif-499', 'naif-4', OrbitalSource.HORIZONS)]);
		const ctx = fakeCtx(credits, null, { systemDrawn: false });
		expect(creditedOrbitArchives(ctx)).toEqual([]);
	});

	it('credits nobody for a probe no archive tracked', () => {
		const credits = new CreditsStore();
		credits.recordOrbitSources([probe('probe-1')]);
		expect(creditedOrbitArchives(fakeCtx(credits, null))).toEqual([]);
	});
});

describe('scopedCredits', () => {
	const map = { bodyId: 'naif-399', systemId: 'naif-3' };

	it('credits the imagery of the system in view', () => {
		expect(scopedCredits(fakeCtx(new CreditsStore(), 'naif-3'), [map])).toEqual([map]);
	});

	it('drops it from solar system scope outwards, with the system still focused', () => {
		expect(scopedCredits(fakeCtx(new CreditsStore(), null), [map])).toEqual([]);
	});

	it('credits a planetary system of another star while it draws beside the Sun', () => {
		const planet = { bodyId: 'x-1-b-1', systemId: 'x-1' };
		const ctx = fakeCtx(new CreditsStore(), 'naif-3', { planetSystemInView: 'x-1' });
		expect(scopedCredits(ctx, [map, planet])).toEqual([map, planet]);
		expect(scopedCredits(fakeCtx(new CreditsStore(), 'naif-3'), [planet])).toEqual([]);
	});
});

describe('focusedModelCredit', () => {
	const credits = new CreditsStore();
	credits.registerModel({
		bodyId: 'probe-1',
		source: 'https://example.org/',
		organisation: 'NASA'
	});

	it('credits the mesh while the body draws with no halo', () => {
		const ctx = fakeCtx(credits, null, { focusedBodyId: 'probe-1', focusedAtFullSize: true });
		expect(focusedModelCredit(ctx)?.organisation).toBe('NASA');
	});

	it('drops the credit once the halo draws', () => {
		const ctx = fakeCtx(credits, null, { focusedBodyId: 'probe-1', focusedAtFullSize: false });
		expect(focusedModelCredit(ctx)).toBeUndefined();
	});
});

describe('attributionChips', () => {
	it('names the agency of each probe, with one chip for every NASA archive', () => {
		const credits = new CreditsStore();
		credits.recordOrbitSources([
			body('naif-499', 'naif-4', OrbitalSource.HORIZONS),
			probe('probe-1', 'naif-pds4'),
			probe('probe-2', 'esa'),
			probe('probe-3', 'jaxa-darts')
		]);
		expect(attributionChips(fakeCtx(credits, null)).orbits).toEqual(['NASA', 'ESA', 'JAXA']);
	});
});
