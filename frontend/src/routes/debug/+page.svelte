<!-- Index of dev-only debug tools. -->
<script lang="ts">
	const pages: { path: string; title: string; note: string }[] = [
		{
			path: '/debug/atmosphere',
			title: 'Atmosphere',
			note: 'Tune body atmosphere shells in a live WebGL scene.'
		},
		{
			path: '/debug/og-preview',
			title: 'OG preview',
			note: 'Preview Open Graph / social cards for sample pages.'
		}
	];
</script>

<main>
	<h1>Debug tools</h1>
	<ul>
		{#each pages as page (page.path)}
			<li>
				<a href={page.path}>{page.title}</a>
				<span>{page.note}</span>
			</li>
		{/each}
	</ul>
</main>

<style>
	main {
		max-width: 40rem;
		margin: 3rem auto;
		padding: 0 1rem;
		font-family: system-ui, sans-serif;
	}
	h1 {
		font-size: 1.5rem;
		margin-bottom: 1.5rem;
	}
	ul {
		list-style: none;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 1rem;
	}
	a {
		font-weight: 600;
	}
	span {
		display: block;
		color: #888;
		font-size: 0.9rem;
	}
</style>
