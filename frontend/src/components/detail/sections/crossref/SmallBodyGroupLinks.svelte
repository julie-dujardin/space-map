<script lang="ts">
	import { type SmallBodyFlagName } from '$lib/fetch/groups/registry';
	import GroupLink from './GroupLink.svelte';
	import FlagGroupLink from './FlagGroupLink.svelte';

	interface Props {
		/** SBDB orbit-class name — its `class-<NAME>` group tile. */
		orbitClass: string;
		/** NEO/PHA flag, if any. */
		flag?: SmallBodyFlagName;
	}
	let { orbitClass, flag }: Props = $props();
</script>

<div class="grid grid-cols-2 gap-2">
	<GroupLink className={orbitClass} class={flag ? '' : 'col-span-2'} />
	{#if flag}
		<FlagGroupLink {flag} />
	{/if}
</div>
