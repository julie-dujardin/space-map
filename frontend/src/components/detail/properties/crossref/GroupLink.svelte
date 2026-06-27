<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import { CLASS_SLUG_PREFIX, orbitClassLabel } from '$lib/charts/orbit-zones';
	import GroupTile from './GroupTile.svelte';

	interface Props {
		/** SBDB OrbitClass enum name (e.g. "MBA") — its `class-<NAME>` group. */
		className: string;
		/** Extra classes, e.g. `col-span-2` to span a 2-col grid row. */
		class?: string;
	}
	let { className, class: classNameProp }: Props = $props();

	let name = $derived(orbitClassLabel(className));
</script>

<GroupTile
	slug={`${CLASS_SLUG_PREFIX}${className}`}
	{name}
	label={m.group()}
	class={classNameProp}
/>
