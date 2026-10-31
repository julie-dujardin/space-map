import { render } from 'svelte/server';
import { describe, expect, it } from 'vitest';
import SparklesIcon from '@lucide/svelte/icons/sparkles';
import SegmentedPill from './SegmentedPill.svelte';

const options = [
	{ value: true, label: 'On', description: 'on', Icon: SparklesIcon },
	{ value: false, label: 'Off', description: 'off', Icon: SparklesIcon }
];
const pill = (props: { shortLabel?: string; alwaysLabelled?: boolean }) =>
	render(SegmentedPill<boolean>, {
		props: { label: 'Clear the sky', options, value: true, onSelect: () => {}, ...props }
	}).body;
const spanOf = (html: string, text: string) =>
	html.match(new RegExp(`<span class="([^"]*)"[^>]*>\\s*${text}`))?.[1] ?? '';

describe('the label of a pill', () => {
	it('goes below 360 px by default', () => {
		const classes = spanOf(pill({ shortLabel: 'Sky' }), 'Sky').split(/\s+/);
		expect(classes).toContain('hidden');
		expect(classes).toContain('min-[360px]:inline');
	});

	it('stays below 360 px on a pill that asks for it', () => {
		const classes = spanOf(pill({ shortLabel: 'Sky', alwaysLabelled: true }), 'Sky').split(/\s+/);
		expect(classes).toContain('inline');
		expect(classes).not.toContain('hidden');
	});

	it('shows none on a phone with no short label', () => {
		expect(pill({})).not.toContain('min-[360px]:inline ');
		expect(spanOf(pill({}), 'Clear the sky').split(/\s+/)).toContain('hidden');
	});
});
