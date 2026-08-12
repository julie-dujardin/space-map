import type { Component } from 'svelte';

/** One end of a segmented pill: what it selects, and what it says it does. */
export interface PillOption<T> {
	value: T;
	label: string;
	description: string;
	Icon: Component<{ class?: string }>;
}
