<!--
  The desktop form of search on the site pages: a plain query with no filters,
  in a panel under the row. A result, or the link to the map's full search,
  opens the map.
-->
<script lang="ts">
	import ArrowRightIcon from '@lucide/svelte/icons/arrow-right';
	import SearchIcon from '@lucide/svelte/icons/search';
	import XIcon from '@lucide/svelte/icons/x';
	import * as m from '$lib/paraglide/messages.js';
	import { isSearchEnabled } from '$lib/search/client';
	import { QuickSearch } from '$lib/search/quick.svelte';
	import { isSearchShortcut, searchShortcutLabel } from '$lib/search/shortcut';
	import { ScrollArea } from '$lib/components/ui/scroll-area/index.js';
	import SearchProof from '../search/SearchProof.svelte';
	import { SITE_COLUMN, SITE_GUTTER } from './site';

	const uid = $props.id();
	const panelId = `site-search-${uid}`;
	const qs = new QuickSearch(`${panelId}-list`);
	const shortcut = searchShortcutLabel();

	let open = $state(false);
	let trigger = $state<HTMLButtonElement>();
	let input = $state<HTMLInputElement>();

	$effect(() => {
		const el = input;
		if (open) el?.focus();
	});

	function close(refocus: boolean) {
		open = false;
		if (refocus) trigger?.focus();
	}

	function onWindowKey(e: KeyboardEvent) {
		// A narrow window hides the row's desktop half, and this with it.
		if (!isSearchShortcut(e) || !trigger?.checkVisibility()) return;
		e.preventDefault();
		if (open) input?.focus();
		else open = true;
	}

	function onInputKey(e: KeyboardEvent) {
		if (e.key === 'Escape') {
			e.preventDefault();
			close(true);
			return;
		}
		qs.onKey(e);
	}
</script>

<svelte:window onkeydown={onWindowKey} />

{#if isSearchEnabled()}
	<button
		bind:this={trigger}
		type="button"
		class="flex h-8 w-8 cursor-pointer items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-accent hover:text-foreground aria-expanded:bg-accent aria-expanded:text-foreground"
		title="{m.search_placeholder()} ({shortcut})"
		aria-label={m.search_placeholder()}
		aria-expanded={open}
		aria-controls={panelId}
		onclick={() => (open ? close(false) : (open = true))}
	>
		<SearchIcon class="size-4" />
	</button>
	{#if open}
		<!-- Hangs from the row's header. The page under it dims, and a click on
		     the page closes it. -->
		<button
			type="button"
			tabindex="-1"
			aria-hidden="true"
			class="absolute inset-x-0 top-full z-40 h-[calc(100dvh-100%)] cursor-default bg-black/30 animate-in fade-in-0"
			onclick={() => close(false)}
		></button>
		<div
			id={panelId}
			class="absolute inset-x-0 top-full z-50 border-b border-border bg-background shadow-lg animate-in fade-in-0 slide-in-from-top-2"
		>
			<div class="{SITE_COLUMN} {SITE_GUTTER} py-4">
				<div
					class="flex h-12 items-center gap-2 rounded-lg border border-border bg-background px-4"
				>
					<SearchIcon class="size-4 shrink-0 text-muted-foreground" />
					<!-- Not type="search": its native cancel button is drawn far heavier
					     than the rest. -->
					<input
						bind:this={input}
						bind:value={qs.query}
						type="text"
						placeholder={m.search_placeholder()}
						aria-label={m.search_placeholder()}
						role="combobox"
						aria-expanded={qs.rows.length > 0}
						aria-controls={qs.listboxId}
						aria-activedescendant={qs.activeIndex >= 0 ? qs.optionId(qs.activeIndex) : undefined}
						aria-autocomplete="list"
						autocomplete="off"
						spellcheck="false"
						enterkeyhint="go"
						onkeydown={onInputKey}
						class="min-w-0 flex-1 bg-transparent text-base outline-none placeholder:text-muted-foreground"
					/>
					{#if qs.query}
						<button
							type="button"
							onclick={() => {
								qs.query = '';
								input?.focus();
							}}
							aria-label={m.search_clear_search()}
							class="shrink-0 cursor-pointer rounded-full p-0.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
						>
							<XIcon class="size-3.5" />
						</button>
					{:else}
						<kbd
							class="pointer-events-none inline-flex h-5 shrink-0 items-center rounded border border-border bg-muted px-1.5 font-mono text-[10px] font-medium text-muted-foreground select-none"
						>
							{shortcut}
						</kbd>
					{/if}
				</div>

				<SearchProof shown={qs.active} class="px-3 pt-2" />

				{#if qs.active}
					<div class="mt-2">
						{#if qs.rows.length > 0}
							<ScrollArea viewportClasses="max-h-[60vh]">
								<div id={qs.listboxId} role="listbox" class="p-1.5">
									{#each qs.groups as group (group.kind)}
										<div role="group" aria-label={group.label} class="mb-2">
											<p
												class="px-2 pt-1 pb-1 text-[11px] font-medium tracking-wide text-muted-foreground uppercase"
											>
												{group.label}
											</p>
											<!-- Rows fill across, then down, so the arrows walk them in
											     reading order. -->
											<ul class="grid grid-cols-2 gap-x-4">
												{#each group.rows as { hit, index } (hit.kind + hit.id)}
													{@const secondary = qs.secondary(hit)}
													<li role="presentation">
														<a
															role="option"
															id={qs.optionId(index)}
															href={qs.href(hit)}
															aria-selected={index === qs.activeIndex}
															tabindex="-1"
															onclick={() => close(false)}
															onmousemove={() => (qs.activeIndex = index)}
															class="block rounded-md px-2 py-1.5 text-start {index ===
															qs.activeIndex
																? 'bg-muted'
																: ''}"
														>
															<span class="block truncate text-sm">{qs.name(hit)}</span>
															{#if secondary}
																<span class="block truncate text-xs text-muted-foreground">
																	{secondary}
																</span>
															{/if}
														</a>
													</li>
												{/each}
											</ul>
										</div>
									{/each}
								</div>
							</ScrollArea>
						{:else if qs.searching}
							<p class="px-4 py-3 text-sm text-muted-foreground">{m.travel_searching()}</p>
						{:else}
							<p class="px-4 py-3 text-sm text-muted-foreground">{m.travel_search_empty()}</p>
						{/if}
						<div class="flex items-center border-t border-border px-2 py-1.5">
							<a
								href={qs.allHref}
								onclick={() => close(false)}
								class="ms-auto flex min-w-0 items-center gap-1.5 rounded-md px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
							>
								<span class="truncate">{m.search_see_all({ query: qs.trimmed })}</span>
								<ArrowRightIcon class="size-3.5 shrink-0 rtl:rotate-180" />
							</a>
						</div>
					</div>
				{:else if qs.trimmed}
					<p class="mt-2 px-4 py-3 text-sm text-muted-foreground">{m.travel_search_more()}</p>
				{/if}
			</div>
		</div>
	{/if}
{/if}
