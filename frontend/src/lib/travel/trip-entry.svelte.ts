/** The planner entry of one panel, reactive. Shared by the header button and
 *  the overview action row so both appear on exactly the same objects. */

import { getContext } from 'svelte';
import { isExtrasolarObjectId } from '$lib/fetch/extrasolar/ids';
import type { AppState } from '$lib/state/app-state.svelte';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import type { BodyData } from '$lib/types/objects';
import { extrasolarTripTarget, travelEntry, type TravelEntry } from './travel-entry';

export class TripEntry {
	/** Null while an extrasolar target resolves, and where no trip reaches it. */
	readonly entry: TravelEntry | null;

	/** Call during component init: it reads the scene and app contexts. */
	constructor(target: () => BodyData, featureId: () => number | null = () => null) {
		const ctx = getContext<ContextManager | undefined>('ctx');
		const appState = getContext<AppState | undefined>('appState');
		const targetId = $derived(target().id);
		/** The star or planet that the planner resolves an extrasolar target to. */
		let awayTarget = $state<BodyData | null>(null);
		$effect(() => {
			const id = targetId;
			awayTarget = null;
			if (!isExtrasolarObjectId(id)) return;
			let cancelled = false;
			void extrasolarTripTarget(id).then((body) => {
				if (!cancelled) awayTarget = body;
			});
			return () => {
				cancelled = true;
			};
		});
		this.entry = $derived(
			isExtrasolarObjectId(targetId)
				? awayTarget && travelEntry(ctx, appState, awayTarget)
				: travelEntry(ctx, appState, target(), featureId())
		);
	}
}
