<script lang="ts">
	/**
	 * An inline link to another body, given only its id.
	 *
	 * The activity block cites bodies rather than naming them — what raises a
	 * tide, what holds a resonance up — so the name comes from the target's own
	 * bundle and arrives after the row does. The id is the fallback text rather
	 * than a blank, so a link never renders as nothing while the fetch is in
	 * flight or if it fails.
	 */
	import { getContext } from 'svelte';
	import Link from './Link.svelte';
	import type { AppState } from '$lib/state/app-state.svelte';
	import type { FocusObject } from '$lib/state/focusable';
	import { fetchObjectDetail } from '$lib/fetch/objects/object-data';
	import { focusClick, focusHref } from '$lib/state/focus-link';

	interface Props {
		/** Backend object id, e.g. `naif-599`. */
		id: string;
	}

	let { id }: Props = $props();

	const appState = getContext<AppState | undefined>('appState');
	const focusObject = getContext<FocusObject | undefined>('focusObject');

	let name = $state<string | null>(null);
	$effect(() => {
		let cancelled = false;
		fetchObjectDetail(id).then((detail) => {
			if (cancelled) return;
			name = detail.localized?.name ?? detail.global?.name ?? null;
		});
		return () => {
			cancelled = true;
		};
	});

	let display = $derived(name ?? id);
	let href = $derived(focusHref(appState, id, display));
</script>

<Link {href} onclick={focusClick(focusObject, id, display)}>{display}</Link>
