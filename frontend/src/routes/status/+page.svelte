<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import SitePage from '../../components/nav/SitePage.svelte';
	import { formatIsoDate, formatIsoDateShort, formatIsoRelative } from '$lib/format/date';
	import { getLocale } from '$lib/host';
	import {
		freshness,
		sections,
		tally,
		type Status,
		type StatusSource
	} from '$lib/status/status-payload';

	interface Props {
		data: { status: Status };
	}

	let { data }: Props = $props();
	const status = $derived(data.status);

	// One instant for the whole render, so every row's age is measured against
	// the same reference and the summary counts agree with the rows.
	const now = Date.now();
	const grouped = $derived(sections(status));
	const counts = $derived(tally(status, now));

	const EM_DASH = '—';

	function records(source: StatusSource): string {
		if (source.record_count === undefined) return EM_DASH;
		return source.record_count.toLocaleString(getLocale());
	}

	/** The age cell carries the state: amber for the two worth acting on. */
	function ageClass(source: StatusSource): string {
		return freshness(source, now) === 'current' ? 'text-foreground' : 'text-status-due';
	}
</script>

<svelte:head>
	<title>{m.status_page_title()} - {m.page_title()}</title>
</svelte:head>

{#snippet age(source: StatusSource)}
	{#if source.downloaded_at}
		{formatIsoRelative(source.checked_at ?? source.downloaded_at, now)}
	{:else}
		{m.status_never_downloaded()}
	{/if}
{/snippet}

<SitePage current="status" title={m.status_page_title()}>
	<div class="text-sm leading-relaxed">
		<p class="-mt-6 mb-2 text-xs text-muted-subtle">
			{m.status_generated({ date: formatIsoDate(status.generated_at) })}
		</p>
		<p class="mt-1.5">
			{m.status_summary_sources({ count: counts.total })} ·
			{m.status_summary_current({ count: counts.current })} ·
			{m.status_summary_due({ count: counts.due })} ·
			{m.status_summary_never({ count: counts.never })}
		</p>

		<!-- One row per source: name, then three right-aligned figures. The
		     header labels them once for the whole page; each section repeats
		     only its own name. -->
		<div
			class="mt-7 flex items-baseline gap-4 border-b border-border pb-1.5 text-xs font-semibold uppercase tracking-wider text-muted-subtle"
		>
			<div class="min-w-0 flex-1">{m.status_column_source()}</div>
			<div class="hidden w-24 shrink-0 text-end sm:block">{m.status_column_records()}</div>
			<div class="hidden w-28 shrink-0 text-end sm:block">{m.status_column_downloaded()}</div>
			<div class="w-28 shrink-0 text-end sm:w-33">{m.status_column_age()}</div>
		</div>

		{#each grouped as section (section.id)}
			<section>
				<h2 class="mt-7 mb-1 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
					{section.label}
				</h2>
				<ul>
					{#each section.sources as source (source.id)}
						<li class="flex items-baseline gap-4 border-b border-border py-2.5">
							<div class="min-w-0 flex-1">
								<a
									href={source.homepage}
									target="_blank"
									rel="noopener noreferrer"
									class="hover:underline underline-offset-2">{source.label}</a
								>
								{#if source.derived}<span class="text-muted-subtle">
										· {m.status_derived()}</span
									>{/if}
								<!-- Phone has room for the name and its age, no more; the
								     other two figures ride under the name instead. -->
								{#if source.downloaded_at}
									<div class="text-xs text-muted-subtle tabular-nums sm:hidden">
										{formatIsoDateShort(source.downloaded_at)}
										{#if source.record_count !== undefined}· {records(source)}{/if}
									</div>
								{/if}
							</div>
							<div class="hidden w-24 shrink-0 text-end text-muted-subtle tabular-nums sm:block">
								{records(source)}
							</div>
							<div
								class="hidden w-28 shrink-0 text-end text-muted-foreground tabular-nums sm:block"
							>
								{source.downloaded_at ? formatIsoDateShort(source.downloaded_at) : EM_DASH}
							</div>
							<div class="w-28 shrink-0 text-end sm:w-33 {ageClass(source)}">
								{#if freshness(source, now) !== 'current'}
									<span
										class="me-2 inline-block size-1.5 rounded-full bg-status-due align-middle"
										aria-hidden="true"
									></span>
								{/if}{@render age(source)}
							</div>
						</li>
					{/each}
				</ul>
			</section>
		{/each}
	</div>
</SitePage>
