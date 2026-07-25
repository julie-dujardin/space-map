<script lang="ts">
	import { groupTypeLabel } from '$lib/format/group';
	import GroupTile from './GroupTile.svelte';
	import BodyTile from './BodyTile.svelte';

	interface Props {
		/** Host body id — its tile opens the body the feature sits on. */
		hostId: string;
		/** Host display name, when the scene already resolved one. */
		hostName?: string;
		/** The feature's type page (`ft-<slug>`), once the group index resolves it. */
		typeSlug?: string;
		typeLabel?: string;
	}
	let { hostId, hostName, typeSlug, typeLabel }: Props = $props();
</script>

<div class="grid grid-cols-2 gap-2">
	{#if typeSlug && typeLabel}
		<GroupTile slug={typeSlug} name={typeLabel} label={groupTypeLabel('feature_type')} />
	{/if}
	<!-- The host tile lands on its Features tab: the feature's neighbours, not
	     the body's overview. -->
	<BodyTile id={hostId} name={hostName} tab="features" class={typeSlug ? '' : 'col-span-2'} />
</div>
