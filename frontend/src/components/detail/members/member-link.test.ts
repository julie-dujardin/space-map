import { describe, expect, it } from 'vitest';
import { systemMemberNames } from './member-link';

describe('systemMemberNames', () => {
	const members = [
		{ name: 'Jupiter', id: 'naif-5', system_name: 'Jupiter system' },
		{ name: 'Mars', id: 'naif-4', system_name: 'Mars system' }
	];

	it('names each system by its page, in the language where it has a name', () => {
		const localized = {
			notable_member_names: { 'naif-5': 'Юпитер', 'naif-4': 'Марс' },
			member_system_names: { 'naif-5': 'Система Юпитера' }
		};
		expect(systemMemberNames(members, localized)).toEqual({
			'naif-5': 'Система Юпитера',
			'naif-4': 'Mars system'
		});
		expect(systemMemberNames(members, null)).toEqual({
			'naif-5': 'Jupiter system',
			'naif-4': 'Mars system'
		});
	});

	it('keeps the planet names of an export without system names', () => {
		const old = members.map(({ name, id }) => ({ name, id }));
		expect(systemMemberNames(old, { notable_member_names: { 'naif-5': 'Юпитер' } })).toEqual({
			'naif-5': 'Юпитер',
			'naif-4': 'Mars'
		});
	});
});
