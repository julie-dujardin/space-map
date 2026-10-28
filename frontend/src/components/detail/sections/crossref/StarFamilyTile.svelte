<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import { groupTypeLabel, starFamilyLabel } from '$lib/format/group';
	import type { StarFamilyLink } from '$lib/fetch/extrasolar/families';
	import GroupTile from './GroupTile.svelte';

	interface Props {
		link: StarFamilyLink;
		/** Extra classes, e.g. `col-span-2` to span a 2-col grid row. */
		class?: string;
	}
	let { link, class: className }: Props = $props();
</script>

<GroupTile
	slug={link.slug}
	name={starFamilyLabel(link.slug)}
	label={link.estimated ? m.crossref_star_family_estimated() : groupTypeLabel('star_family')}
	class={className}
/>
