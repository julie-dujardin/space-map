<!--
  The contents of a long page, in the page margin, so they show only where the
  margin can hold them. The parent is `relative` and as tall as the page, so
  the list stays in view down its whole length.
-->
<script lang="ts" module>
	/** `id` is that of the heading the entry goes to. */
	export interface ContentsEntry {
		id: string;
		label: string;
		children?: ContentsEntry[];
	}
</script>

<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';

	interface Props {
		entries: ContentsEntry[];
	}

	let { entries }: Props = $props();
</script>

{#snippet link(entry: ContentsEntry)}
	<a href="#{entry.id}" class="hover:text-foreground">{entry.label}</a>
{/snippet}

<nav
	aria-label={m.credits_contents()}
	class="absolute inset-y-0 end-full me-8 hidden w-44 xl:block"
>
	<ul class="sticky top-10 space-y-3 text-xs leading-snug text-muted-foreground">
		{#each entries as group (group.id)}
			<li>
				<span class="font-medium text-foreground">{@render link(group)}</span>
				{#if group.children}
					<ul class="mt-1.5 space-y-1.5">
						{#each group.children as entry (entry.id)}
							<li>{@render link(entry)}</li>
						{/each}
					</ul>
				{/if}
			</li>
		{/each}
	</ul>
</nav>
