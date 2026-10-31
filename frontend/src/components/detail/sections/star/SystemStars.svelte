<!--
  The stars of a star system, as its tree. A node's page lists its own members.
  The page of a star in a system lists the whole system, led by a link to it,
  with the star itself marked.
-->
<script lang="ts">
	import { getContext } from 'svelte';
	import * as m from '$lib/paraglide/messages.js';
	import MemberRow from '../../members/MemberRow.svelte';
	import Section from '../kit/Section.svelte';
	import { extrasolarObjectId } from '$lib/fetch/extrasolar/ids';
	import type { SystemNode } from '$lib/fetch/extrasolar/systems';
	import { targetClick, targetHref } from '$lib/state/focus-link';
	import type { AppState } from '$lib/state/app-state.svelte';
	import type { FocusFeature, FocusObject } from '$lib/state/focusable';
	import { systemRows, type StarSystem } from '$lib/state/star-system';
	import { memberFigures } from './system-rows';

	interface Props {
		system: StarSystem;
		/** The node whose page this is. */
		node?: SystemNode | null;
		/** The star whose page this is. */
		star?: number | null;
	}

	let { system, node = null, star = null }: Props = $props();

	/** Past this depth the rows keep their indent: the names need the width. */
	const MAX_INDENT = 3;

	const appState = getContext<AppState | undefined>('appState');
	const focusObject = getContext<FocusObject | undefined>('focusObject');
	const focusFeature = getContext<FocusFeature | undefined>('focusFeature');
	let nav = $derived({ appState, focusObject, focusFeature });

	let rootId = $derived(system.root.id);
	let rows = $derived(systemRows(system, node?.id ?? rootId));

	function link(id: number, name: string) {
		const target = { id: extrasolarObjectId(id) };
		return { href: targetHref(appState, target, name), onclick: targetClick(nav, target, name) };
	}

	function indent(depth: number): string {
		return `padding-inline-start: calc(0.25rem + ${Math.min(depth, MAX_INDENT)} * 1.25rem)`;
	}
</script>

{#snippet list()}
	<ul class="flex flex-col">
		{#each rows as row, i (i)}
			{@const { id } = row.member}
			{@const figures = memberFigures(row)}
			{@const own = id === star}
			<MemberRow
				name={row.name}
				tile={row.letter}
				style={indent(row.depth)}
				valuesClass="tabular-nums"
				aria-current={own ? 'page' : undefined}
				{...id === null || own ? {} : link(id, row.name)}
			>
				{#if figures.what}<span>{figures.what}</span>{/if}
				{#if figures.where}<span class="text-muted-foreground">{figures.where}</span>{/if}
			</MemberRow>
		{/each}
	</ul>
{/snippet}

{#if rows.length > 0}
	{#if node}
		<Section title={m.system_stars()} titleMeta={String(node.stars)} header={list} />
	{:else}
		{@const { href, onclick } = link(rootId, system.name)}
		<Section
			title={system.name}
			titleMeta={m.system_star_count({ count: system.root.stars })}
			titleHref={href}
			onActivate={onclick}
			header={list}
		/>
	{/if}
{/if}
