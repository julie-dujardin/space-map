<script lang="ts">
	import { Separator } from '$lib/components/ui/separator/index.js';
	import type { ChildGroupEntry } from '$lib/fetch/groups/details';
	import { categoryLabel, CATEGORY_SLUG_PREFIX, type GroupType } from '$lib/fetch/groups/registry';
	import { groupTypeLabelPlural } from '$lib/format/group';
	import { classNameFromSlug, orbitClassLabel } from '$lib/charts/orbit-zones';
	import ZoneChip from './kit/ZoneChip.svelte';

	interface Props {
		childGroups: ChildGroupEntry[];
	}
	let { childGroups }: Props = $props();

	// Categories and orbit classes name from frontend i18n keys (the export name
	// is English-only / a bare slug for QID-less classes); others use the export name.
	function childName(c: ChildGroupEntry): string {
		const slug = c.primary_id ?? '';
		if (slug.startsWith(CATEGORY_SLUG_PREFIX)) return categoryLabel(slug);
		const className = classNameFromSlug(slug);
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
