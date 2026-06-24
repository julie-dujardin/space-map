<script lang="ts">
	import { Separator } from '$lib/components/ui/separator/index.js';
	import type { ChildGroupEntry } from '$lib/fetch/groups/details';
	import type { GroupType } from '$lib/fetch/groups/registry';
	import { groupTypeLabelPlural } from '$lib/format/group';
	import { classNameFromSlug, orbitClassLabel } from '$lib/charts/orbit-zones';
	import ZoneChip from './ZoneChip.svelte';

	interface Props {
		childGroups: ChildGroupEntry[];
	}
	let { childGroups }: Props = $props();

	// Orbit-class names live in the frontend `orbit_class_*` i18n keys, not the
	// export (whose Wikidata fallback leaves QID-less classes like IGSO/VHEO as
	// the raw slug). Other child types use their exported localized name.
	function childName(c: ChildGroupEntry): string {
		const className = classNameFromSlug(c.primary_id ?? '');
		return className != null ? orbitClassLabel(className) : c.name;
	}

	// Section by child type (orbit classes vs constellations …), preserving the
	// export's order within each section.
	let sections = $derived.by(() => {
		const byRole = new Map<GroupType, ChildGroupEntry[]>();
		for (const c of childGroups) {
			if (!c.primary_id) continue;
			const arr = byRole.get(c.role) ?? [];
			arr.push(c);
			byRole.set(c.role, arr);
		}
		return [...byRole.entries()];
	});
</script>

{#each sections as [role, items] (role)}
	<div class="flex flex-col gap-1.5">
		<h3 class="text-sm font-medium">{groupTypeLabelPlural(role)}</h3>
		<Separator />
		<div class="flex flex-wrap gap-1.5 pt-0.5">
			{#each items as c (c.primary_id)}
				<ZoneChip slug={c.primary_id ?? ''} name={childName(c)} n={c.n} />
			{/each}
		</div>
	</div>
{/each}
