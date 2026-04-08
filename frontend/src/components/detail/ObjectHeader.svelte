<script lang="ts">
	import { Badge } from '$lib/components/ui/badge/index.js';
	import * as m from '$lib/paraglide/messages.js';
	import type { GlobalObjectData, LocalizedObjectData } from '$lib/fetch/objects/object-data';

	interface Props {
		global: GlobalObjectData | null;
		localized: LocalizedObjectData | null;
		fallbackName: string | null;
	}

	let { global, localized, fallbackName }: Props = $props();

	let name = $derived(localized?.name ?? global?.name ?? fallbackName ?? m.unknown());
	let image = $derived(
		localized?.wikipedia?.thumbnail ??
			global?.wikidata?.image?.[0] ??
			global?.wikidata?.logo_image?.[0]
	);
	let types = $derived(localized?.instance_of?.length ? localized.instance_of : null);
	let description = $derived(localized?.description ?? localized?.wikipedia?.description);
	let aliases = $derived(localized?.aliases);

	function ucfirst(s: string): string {
		return s.charAt(0).toUpperCase() + s.slice(1);
	}
</script>

<div class="flex flex-col gap-3">
	{#if image}
		<img src={image} alt={name} class="w-full max-h-48 object-cover rounded-md" />
	{/if}
	<div class="flex flex-wrap items-start gap-2">
		{#if types}
			{#each types as t, i (i)}
				<Badge variant="secondary" class="shrink-0 text-xs">{ucfirst(t.name)}</Badge>
			{/each}
		{:else}
			<Badge variant="secondary" class="shrink-0 text-xs">{ucfirst(m.object())}</Badge>
		{/if}
	</div>
	{#if description}
		<p class="text-sm text-muted-foreground">{ucfirst(description)}</p>
	{/if}
	{#if aliases && aliases.length > 0}
		<p class="text-xs text-muted-foreground">{m.also_known_as({ aliases: aliases.join(', ') })}</p>
	{/if}
</div>
