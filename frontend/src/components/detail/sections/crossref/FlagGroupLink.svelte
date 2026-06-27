<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import { SMALL_BODY_FLAG_SLUG_PREFIX, type SmallBodyFlagName } from '$lib/fetch/groups/registry';
	import GroupTile from './GroupTile.svelte';

	interface Props {
		/** Small-body flag (e.g. "neo", "pha") — its `flag-<name>` group. */
		flag: SmallBodyFlagName;
		/** Extra classes, e.g. `col-span-2` to span a 2-col grid row. */
		class?: string;
	}
	let { flag, class: className }: Props = $props();

	const FLAG_NAMES: Record<SmallBodyFlagName, () => string> = {
		neo: m['group_name_flag-neo'],
		pha: m['group_name_flag-pha']
	};
	let name = $derived(FLAG_NAMES[flag]());
</script>

<GroupTile
	slug={`${SMALL_BODY_FLAG_SLUG_PREFIX}${flag}`}
	{name}
	label={m.group()}
	class={className}
/>
