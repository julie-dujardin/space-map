<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import { familyLabel, groupTypeLabel } from '$lib/format/group';
	import type { FamilyLink, FamilyType } from '$lib/fetch/extrasolar/families';
	import GroupTile from './GroupTile.svelte';

	interface Props {
		link: FamilyLink;
		/** Extra classes, e.g. `col-span-2` to span a 2-col grid row. */
		class?: string;
	}
	let { link, class: className }: Props = $props();

	const ESTIMATED: Record<FamilyType, () => string> = {
		star_family: m.crossref_star_family_estimated,
		planet_family: m.crossref_planet_family_estimated
	};
</script>

<GroupTile
	slug={link.slug}
	name={familyLabel(link.slug)}
	label={link.estimated ? ESTIMATED[link.type]() : groupTypeLabel(link.type)}
	class={className}
/>
