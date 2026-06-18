<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';

	// Curated shortcuts beside the search bar / detail sidebar. Objects fly the
	// camera; groups open the /g view.
	type FeaturedItem =
		| { kind: 'object'; id: string; label: string }
		| { kind: 'group'; slug: string; label: string };

	type Props = {
		onObject: (id: string, name: string) => void;
		onGroup: (slug: string, name: string) => void;
	};

	let { onObject, onGroup }: Props = $props();

	const items: FeaturedItem[] = [
		{ kind: 'object', id: 'norad_satcat-25544', label: m.featured_iss() },
		{ kind: 'group', slug: 'class-MBA', label: m.featured_main_belt() },
		{ kind: 'object', id: 'naif-499', label: m.featured_mars() },
		{ kind: 'group', slug: 'const-starlink', label: m.featured_starlink() },
		{ kind: 'object', id: 'probe-121737217', label: m.featured_artemis_2() }
	];

	function pick(item: FeaturedItem) {
		if (item.kind === 'group') onGroup(item.slug, item.label);
		else onObject(item.id, item.label);
	}
</script>

<div
	class="flex gap-1.5 overflow-x-auto pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
	aria-label={m.featured_label()}
>
	{#each items as item (item.label)}
		<button
			type="button"
			class="inline-flex h-7 shrink-0 items-center rounded-full border border-border bg-popover/90 px-2.5 text-xs whitespace-nowrap text-foreground shadow-lg backdrop-blur-md transition-colors hover:bg-accent"
			onclick={() => pick(item)}
		>
			{item.label}
		</button>
	{/each}
</div>
