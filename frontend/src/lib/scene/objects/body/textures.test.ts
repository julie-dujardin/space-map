import { afterEach, describe, expect, it, vi } from 'vitest';
import { configureHost } from '$lib/host';
import { ObjectType } from '$lib/types/objects';
import type { BodyObjects } from '../../types';
import { loadBodyLabel } from './textures';

/** The label of a promoted body takes its name after the build. */

const { starPageName, setLabelName } = vi.hoisted(() => ({
	starPageName: vi.fn(),
	setLabelName: vi.fn()
}));
vi.mock('$lib/fetch/extrasolar/star-name', () => ({ starPageName }));
vi.mock('../../label/factory', () => ({
	getLabelVariant: () => 'major',
	hasLargeLabel: () => true,
	setLabelName
}));

function starLabel(name: string | null, locale = 'en') {
	configureHost({
		locale: () => locale,
		bodyHref: (id: string, n: string) => `/x/${id}/${n}`
	});
	const element = { href: '/x/x-7' };
	const record = { id: 7 };
	const bo = {
		label: { element },
		body: {
			data: { id: 'x-7', name, objectType: ObjectType.EXTRASOLAR },
			extrasolar: { record }
		}
	} as unknown as BodyObjects;
	return { bo, element, record };
}

afterEach(() => vi.resetAllMocks());

describe('the label of a star', () => {
	it('takes the composed name of a system with no name, in its link too', async () => {
		const { bo, element, record } = starLabel(null);
		starPageName.mockResolvedValue('HIP 1234');
		await loadBodyLabel(bo);
		expect(starPageName).toHaveBeenCalledWith(record);
		expect(setLabelName).toHaveBeenCalledWith(bo, 'HIP 1234', 'major', true);
		expect(bo.body.data.name).toBe('HIP 1234');
		expect(element.href).toBe('/x/x-7/HIP 1234');
	});

	it('keeps the name it has in English, with no fetch', async () => {
		const { bo } = starLabel('Sirius');
		await loadBodyLabel(bo);
		expect(starPageName).not.toHaveBeenCalled();
	});

	it('takes the name in the reader language, and keeps its link', async () => {
		const { bo, element } = starLabel('Sirius', 'fr');
		starPageName.mockResolvedValue('Sirius (fr)');
		await loadBodyLabel(bo);
		expect(bo.body.data.name).toBe('Sirius (fr)');
		expect(element.href).toBe('/x/x-7');
	});

	it('stays as it is when no name loads', async () => {
		const { bo } = starLabel(null);
		starPageName.mockRejectedValue(new Error('no file'));
		await loadBodyLabel(bo);
		expect(setLabelName).not.toHaveBeenCalled();
		expect(bo.body.data.name).toBeNull();
	});
});
