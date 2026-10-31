<script lang="ts">
	import { groupTypeLabel } from '$lib/format/group';
	import GroupTile from './GroupTile.svelte';

	interface Props {
		/** The feature's type page (`ft-<slug>`), once the group index resolves it. */
		typeSlug?: string;
		typeLabel?: string;
	}
	let { typeSlug, typeLabel }: Props = $props();
</script>

{#if typeSlug && typeLabel}
	<div class="grid grid-cols-2 gap-2">
		<GroupTile
			slug={typeSlug}
			name={typeLabel}
			label={groupTypeLabel('feature_type')}
			class="col-span-2"
		/>
	</div>
{/if}
