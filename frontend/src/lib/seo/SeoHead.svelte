<script lang="ts">
	import type { SeoMeta } from './meta';

	let { seo }: { seo: SeoMeta } = $props();

	function jsonLdScript(s: SeoMeta): string {
		const ld: Record<string, unknown> = {
			'@context': 'https://schema.org',
			'@type': 'WebPage',
			name: s.title,
			description: s.description,
			url: s.canonical
		};
		if (s.image) ld.image = s.image;
		// Escape `<` so a value with a closing script tag can't break out of the block.
		const json = JSON.stringify(ld).replace(/</g, '\\u003c');
		return '<script type="application/ld+json">' + json + '</' + 'script>';
	}
</script>

<svelte:head>
	<title>{seo.title}</title>
	<meta name="description" content={seo.description} />
	<link rel="canonical" href={seo.canonical} />

	<meta property="og:site_name" content="Space Map" />
	<meta property="og:type" content={seo.ogType} />
	<meta property="og:url" content={seo.canonical} />
	<meta property="og:title" content={seo.title} />
	<meta property="og:description" content={seo.description} />
	{#if seo.image}
		<meta property="og:image" content={seo.image} />
	{/if}

	<meta name="twitter:card" content={seo.image ? 'summary_large_image' : 'summary'} />
	<meta name="twitter:title" content={seo.title} />
	<meta name="twitter:description" content={seo.description} />
	{#if seo.image}
		<meta name="twitter:image" content={seo.image} />
	{/if}

	<!-- Safe: JSON.stringify of controlled fields with every `<` escaped to its
	     unicode form, so no markup can be injected. -->
	<!-- eslint-disable-next-line svelte/no-at-html-tags -->
	{@html jsonLdScript(seo)}
</svelte:head>
