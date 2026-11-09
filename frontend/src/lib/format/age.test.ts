import { describe, expect, it } from 'vitest';
import { ageNote } from './activity';
import { ageParts, formedAgo, spellAge } from './age';
import { fixed, joinParts } from './quantities';
import { withBounds } from './star';

/** The text without its bidi isolates and with plain spaces. */
const INVISIBLES = new RegExp('[\\u2060\\u2066-\\u2069]', 'g');
const NO_BREAK = new RegExp('\\u00a0', 'g');
const plain = (value: string) => value.replace(INVISIBLES, '').replace(NO_BREAK, ' ');

describe('an age in words', () => {
	it('reads in billions or millions of years by its value', () => {
		expect(plain(spellAge({ value: 3.5e9 }))).toBe('3.5 billion years ago');
		expect(plain(spellAge({ value: 6e8 }))).toBe('600 million years ago');
		expect(plain(spellAge({ value: 5.3e4 }))).toBe('53 thousand years ago');
	});

	it('gives its range at the scale of its value', () => {
		// Venus's surface age: 250 Ma to 1 Ga across crater models.
		expect(plain(spellAge({ value: 6e8, range: [2.5e8, 1e9] }))).toBe(
			'600 (250–1,000) million years ago'
		);
	});

	it('reads an upper limit as one', () => {
		expect(plain(spellAge({ value: 1e8, upper_limit: true }))).toBe(
			'Less than 100 million years ago'
		);
		expect(plain(spellAge({ value: 1.5e9, upper_limit: true }))).toBe(
			'Less than 1.5 billion years ago'
		);
	});

	it('keeps what the source said, but not a second "upper limit"', () => {
		expect(plain(ageNote({ value: 1e8, upper_limit: true }))).toBe(
			'Less than 100 million years ago'
		);
		expect(plain(ageNote({ value: 6e8, modelled: true }))).toBe(
			"600 million years ago — Scaled from another body's record."
		);
	});
});

describe('a scale of an age', () => {
	it('is the same for the row and its words', () => {
		expect(plain(joinParts(ageParts(6e8)))).toBe('600 Ma');
		expect(plain(joinParts(ageParts(9.996e8)))).toBe('1 Ga');
		expect(plain(spellAge({ value: 9.996e8 }))).toBe('1 billion years ago');
		expect(plain(joinParts(ageParts(500)))).toBe('500 a');
	});
});

describe('when a star formed', () => {
	const bounded = (gyr: number, low: number, high: number) =>
		plain(formedAgo(withBounds(gyr, low, high)));

	it('says the age and its bounds in billions of years', () => {
		expect(bounded(13.28, 11.93, 13.5)).toBe('Formed 13.28 (11.93–13.50) billion years ago');
		expect(bounded(1, 0.5, 1.6)).toBe('Formed 1.00 (0.50–1.60) billion years ago');
	});

	it('says an age under 1 Gyr in billions too, as the row does', () => {
		expect(bounded(0.35, 0.2, 0.6)).toBe('Formed 0.35 (0.20–0.60) billion years ago');
		expect(plain(formedAgo(fixed(0.9996, 2)))).toBe('Formed 1.00 billion years ago');
	});
});
