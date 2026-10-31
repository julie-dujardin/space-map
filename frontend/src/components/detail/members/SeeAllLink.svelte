<script lang="ts">
	import { getContext } from 'svelte';
	import ArrowRightIcon from '@lucide/svelte/icons/arrow-right';
	import * as m from '$lib/paraglide/messages.js';
	import { categoryLabel } from '$lib/format/group';
	import { groupClick, groupHref } from '$lib/state/focus-link';
	import type { AppState } from '$lib/state/app-state.svelte';

	interface Props {
		/** The category this section is a sample of. */
		slug: string;
		/** The section's heading, for a screen reader. */
		heading: string;
	}
	let { slug, heading }: Props = $props();

	const appState = getContext<AppState | undefined>('appState');
	let name = $derived(categoryLabel(slug));
</script>

<a
	href={groupHref(appState, slug, name)}
	onclick={groupClick(appState, slug, name)}
	class="text-muted-foreground hover:text-foreground inline-flex shrink-0 items-center gap-1 text-xs"
>
	{m.members_see_all()}
	<span class="sr-only">— {heading}</span>
	<ArrowRightIcon class="size-3 rtl:rotate-180" />
</a>
