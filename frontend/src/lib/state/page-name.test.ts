import { describe, expect, it } from 'vitest';
import { groupPageName, objectPageName } from './page-name';

const pair = (global: string | undefined, localized?: string) => ({
	global: global === undefined ? null : { name: global },
	localized: localized === undefined ? null : { name: localized }
});

describe('objectPageName', () => {
	it('takes the localized name before the catalogue name', () => {
		expect(objectPageName('spkid-20177049', pair('2003 EE16', '(177049) 2003 EE16'), null)).toBe(
			'(177049) 2003 EE16'
		);
		expect(objectPageName('spkid-20177049', pair('2003 EE16'), null)).toBe('2003 EE16');
	});

	it('is empty for an object the export gives no name', () => {
		expect(objectPageName('norad_satcat-1', pair(undefined), null)).toBe('');
	});

	it('names the page of a planetary barycenter after the system of its primary', () => {
		expect(objectPageName('naif-5', pair('Jupiter Barycenter'), pair('Jupiter'))).toBe(
			'Jupiter system'
		);
		expect(objectPageName('naif-3', pair('Earth-Moon Barycenter'), pair('Earth'))).toBe(
			'Earth–Moon system'
		);
	});

	it('keeps the own name of a barycenter whose primary has none', () => {
		expect(objectPageName('naif-5', pair('Jupiter Barycenter'), null)).toBe('Jupiter Barycenter');
	});
});

describe('groupPageName', () => {
	it('takes the name of the localized bundle', () => {
		expect(groupPageName('const-starlink', 'Starlink')).toBe('Starlink');
	});

	it('shows the label of a category, not its bundle name', () => {
		expect(groupPageName('cat-moons', 'Natural satellites')).toBe('Moons');
	});

	it('falls back on the label of the slug', () => {
		expect(groupPageName('class-APO', undefined)).toBe('Apollo');
	});
});
