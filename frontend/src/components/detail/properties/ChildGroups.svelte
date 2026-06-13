<script lang="ts">
	import { getContext } from 'svelte';
	import { Separator } from '$lib/components/ui/separator/index.js';
	import type { AppState } from '$lib/state/app-state.svelte';
	import type { ChildGroupEntry } from '$lib/fetch/groups/details';
	import type { GroupType } from '$lib/fetch/groups/registry';
	import { applyGroup, serializeUrl } from '$lib/state/url';
	import { groupTypeLabel } from '$lib/format/group';
	import { formatCompactNumber } from '$lib/format/quantities';
	import { classNameFromSlug, orbitClassLabel } from '$lib/charts/orbit-zones';

	interface Props {
		childGroups: ChildGroupEntry[];
	}
	let { childGroups }: Props = $props();

	const appState = getContext<AppState | undefined>('appState');

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

	function href(slug: string, name: string): string | undefined {
		return appState ? serializeUrl(applyGroup(appState.view, slug, name)) : undefined;
	}

	// Plain left-click swaps via appState; modifier-clicks fall through to the
	// browser. Mirrors Orbital / GroupProperties.
	function onClick(e: MouseEvent, slug: string, name: string) {
		if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
		if (!appState) return;
		e.preventDefault();
		appState.setGroup(slug, name);
	}
</script>

{#each sections as [role, items] (role)}
	<div class="flex flex-col gap-1.5">
		<h3 class="text-sm font-medium">{groupTypeLabel(role)}</h3>
		<Separator />
		<div class="flex flex-wrap gap-1.5 pt-0.5">
			{#each items as c (c.primary_id)}
				{@const name = childName(c)}
				<a
					href={href(c.primary_id ?? '', name)}
					onclick={(e) => onClick(e, c.primary_id ?? '', name)}
					class="border-border/60 hover:bg-muted/60 flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs transition-colors"
				>
					<span class="font-medium">{name}</span>
					{#if c.n > 0}
						<span class="text-muted-foreground tabular-nums">{formatCompactNumber(c.n)}</span>
					{/if}
				</a>
			{/each}
		</div>
	</div>
{/each}
