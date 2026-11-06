import { describe, expect, it } from 'vitest';
import { MarchBudget } from './budget';

describe('the march budget', () => {
	it('grows on fast frames up to the whole map', () => {
		const budget = new MarchBudget(512);
		for (let i = 0; i < 40; i++) budget.note(16.7);
		expect(budget.rows).toBe(512);
	});

	it('halves on a slow frame and stays under where it went slow', () => {
		const budget = new MarchBudget(512);
		for (let i = 0; i < 40; i++) budget.note(16.7);
		budget.note(40);
		expect(budget.rows).toBe(256);
		for (let i = 0; i < 10; i++) budget.note(16.7);
		expect(budget.rows).toBeLessThan(512);
		for (let i = 0; i < 200; i++) budget.note(16.7);
		expect(budget.rows).toBe(512);
	});

	it('keeps a few rows on a device that is always slow', () => {
		const budget = new MarchBudget(256);
		for (let i = 0; i < 40; i++) budget.note(60);
		expect(budget.rows).toBe(4);
	});
});
