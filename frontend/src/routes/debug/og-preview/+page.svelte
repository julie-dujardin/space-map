<!--
  Dev tool: previews Open Graph / social-card output for a representative sample
  of pages. Fetches each page's rendered HTML live (same-origin, client-side),
  parses its og:* meta, and renders a link-preview mockup. Each card links to
  the real page.
-->
<script lang="ts">
	import { onMount } from 'svelte';

	interface Sample {
		path: string;
		tier: 'free' | 'credit' | 'drop' | 'none' | 'minimal' | 'auto';
		note: string;
	}
	interface Card extends Sample {
		status?: number;
		title?: string;
		description?: string;
		image?: string;
		twitter?: string;
		error?: string;
	}

	// One per behaviour: curated tiers, Wikidata-less long tail, and groups.
	const SAMPLES: Sample[] = [
		{ path: '/b/399', tier: 'free', note: 'planet — attribution-free image' },
		{ path: '/b/301', tier: 'credit', note: 'Moon — credit-tier image + front-loaded credit' },
		{ path: '/s/20006257', tier: 'credit', note: 'asteroid shape model (CC BY)' },
		{ path: '/e/31601', tier: 'drop', note: 'credit image, no artist → no image' },
		{ path: '/b/999999999', tier: 'minimal', note: 'unknown id → minimal fallback' },
		// No Wikidata description → description auto-built from exported data.
		// One card per root template branch (see $lib/seo/meta.ts).
		{ path: '/s/3376041', tier: 'auto', note: 'near-Earth asteroid — H-estimated size' },
		{ path: '/s/20826946', tier: 'auto', note: 'near-Earth asteroid — spectral type' },
		{ path: '/s/20244979', tier: 'auto', note: 'main-belt asteroid — measured diameter' },
		{ path: '/s/1001668', tier: 'auto', note: 'comet — first-observed year only' },
		{ path: '/b/555', tier: 'auto', note: 'moon — parent + discovery year' },
		{ path: '/e/36964', tier: 'auto', note: 'orbital debris — launch year + orbit' },
		{ path: '/p/41984000', tier: 'auto', note: 'spacecraft — parent mission' },
		// Groups.
		{ path: '/g/const-starlink', tier: 'free', note: 'group — attribution-free' },
		{ path: '/g/const-iridium', tier: 'none', note: 'group — no image available' },
		{ path: '/g/const-planet-skysat', tier: 'credit', note: 'group — credited image' },
		{ path: '/g/lv-shavit', tier: 'drop', note: 'group — uncreditable → no image' }
	];

	let cards = $state<Card[]>([]);
	let loading = $state(false);

	function metaOf(doc: Document, sel: string): string {
		return doc.querySelector(sel)?.getAttribute('content') ?? '';
	}

	async function fetchCard(s: Sample): Promise<Card> {
		try {
			const res = await fetch(s.path, { headers: { accept: 'text/html' } });
			const doc = new DOMParser().parseFromString(await res.text(), 'text/html');
			return {
				...s,
				status: res.status,
				title: metaOf(doc, 'meta[property="og:title"]'),
				description: metaOf(doc, 'meta[property="og:description"]'),
				image: metaOf(doc, 'meta[property="og:image"]'),
				twitter: metaOf(doc, 'meta[name="twitter:card"]')
			};
		} catch (e) {
			return { ...s, error: String(e) };
		}
	}

	async function load() {
		loading = true;
		cards = await Promise.all(SAMPLES.map(fetchCard));
		loading = false;
	}

	onMount(load);

	// Split a leading "Image: … (License)." credit so it can be highlighted.
	function creditParts(desc: string | undefined): { credit: string; rest: string } {
		const m = desc?.match(/^(Image: .*? \([^)]*\)\.)(.*)$/);
		return m ? { credit: m[1], rest: m[2] } : { credit: '', rest: desc ?? '' };
	}
	function host(u: string | undefined): string {
		try {
			return u ? new URL(u, location.origin).host : location.host;
		} catch {
			return location.host;
		}
	}
</script>

<div class="wrap">
	<header>
		<div>
			<h1>OG card preview</h1>
			<p class="sub">
				Live from the dev server · attribution-free serves an image; credit-tier front-loads a text
				credit; uncreditable / no-image degrade to a plain card. <b>auto</b> cards have no Wikidata description
				and get one built from exported data.
			</p>
		</div>
		<button onclick={load} disabled={loading}>{loading ? 'Loading…' : 'Refresh'}</button>
	</header>

	<div class="grid">
		{#each cards as c (c.path)}
			{@const parts = creditParts(c.description)}
			<div class="item">
				<div class="meta">
					<span class="tag {c.tier}">{c.tier}</span>
					<a class="path" href={c.path} target="_blank" rel="noreferrer">{c.path}</a>
					<span class="note">· {c.note}</span>
				</div>

				<a
					class="card"
					class:summary={!c.image}
					class:err={c.error}
					href={c.path}
					target="_blank"
					rel="noreferrer"
				>
					{#if c.error}
						<div class="body"><div class="desc">{c.error}</div></div>
					{:else}
						{#if c.image}
							<img class="img" src={c.image} alt="" loading="lazy" />
						{/if}
						<div class="body">
							<div class="domain">{host(c.image)}</div>
							<div class="title">{c.title}</div>
							<div class="desc">
								{#if parts.credit}<span class="credit-hl">{parts.credit}</span>{/if}{parts.rest}
							</div>
						</div>
					{/if}
				</a>

				<div class="meta small">
					twitter:card=<b>{c.twitter || '—'}</b> · og:image=<b>{c.image ? 'yes' : 'none'}</b> · http
					{c.status ?? '—'}
				</div>
			</div>
		{/each}
	</div>
</div>

<style>
	.wrap {
		--bg: #0f1115;
		--card: #191c22;
		--line: #2b2f38;
		--text: #e7e9ee;
		--muted: #9aa1ad;
		/* html/body lock overflow for the 3D app, so own the scroll here. */
		position: fixed;
		inset: 0;
		overflow-y: auto;
		background: var(--bg);
		color: var(--text);
		padding: 24px;
		font:
			14px/1.45 system-ui,
			sans-serif;
	}
	header {
		max-width: 1200px;
		margin: 0 auto 20px;
		display: flex;
		align-items: flex-start;
		gap: 16px;
	}
	h1 {
		font-size: 18px;
		margin: 0;
	}
	.sub {
		color: var(--muted);
		margin: 4px 0 0;
		max-width: 70ch;
	}
	button {
		margin-left: auto;
		background: #21262d;
		color: var(--text);
		border: 1px solid var(--line);
		border-radius: 6px;
		padding: 6px 14px;
		cursor: pointer;
		font: inherit;
	}
	button:hover:not(:disabled) {
		background: #2b313a;
	}
	.grid {
		max-width: 1200px;
		margin: 0 auto;
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
		gap: 20px;
	}
	.item {
		display: flex;
		flex-direction: column;
		gap: 8px;
	}
	.meta {
		display: flex;
		align-items: center;
		gap: 8px;
		flex-wrap: wrap;
		font-size: 12px;
		color: var(--muted);
	}
	.meta.small b {
		color: var(--text);
	}
	.tag {
		font-weight: 600;
		border-radius: 999px;
		padding: 1px 8px;
		font-size: 11px;
		color: #0f1115;
	}
	.tag.free {
		background: #3fb950;
	}
	.tag.credit {
		background: #d29922;
	}
	.tag.auto {
		background: #58a6ff;
	}
	.tag.drop,
	.tag.none,
	.tag.minimal {
		background: #8b949e;
	}
	.path {
		font-family: ui-monospace, monospace;
		color: var(--text);
		text-decoration: none;
	}
	.path:hover {
		text-decoration: underline;
	}
	.note {
		color: var(--muted);
	}
	.card {
		display: block;
		border: 1px solid var(--line);
		border-radius: 12px;
		overflow: hidden;
		background: var(--card);
		color: inherit;
		text-decoration: none;
	}
	.card:hover {
		border-color: #3d444d;
	}
	.img {
		width: 100%;
		aspect-ratio: 1.91 / 1;
		object-fit: cover;
		display: block;
		background: #0b0d11;
		border-bottom: 1px solid var(--line);
	}
	.body {
		padding: 12px 14px;
	}
	.summary .body {
		border-left: 4px solid #d29922;
	}
	.err .body {
		border-left: 4px solid #f85149;
	}
	.domain {
		color: var(--muted);
		font-size: 12px;
	}
	.title {
		font-weight: 600;
		margin: 2px 0 4px;
	}
	.desc {
		color: var(--muted);
	}
	.credit-hl {
		color: #e3b341;
		font-weight: 600;
	}
</style>
