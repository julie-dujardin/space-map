/** @type {import('dependency-cruiser').IConfiguration} */
module.exports = {
	forbidden: [
		{
			name: 'core-boundary',
			comment:
				'src/lib/{scene,math,fetch} is the embeddable core (future SDK). Nothing it reaches, ' +
				'directly or transitively, may depend on SvelteKit, the app UI stack, or the i18n bundles — ' +
				'inject those through src/lib/host.ts instead.',
			severity: 'error',
			from: { path: '^src/lib/(scene|math|fetch)/', pathNot: '\\.test\\.ts$' },
			to: {
				path:
					'^\\$app/|^\\$env/|(^\\$lib|^src/lib)/paraglide/|^src/lib/components/|^src/components/|\\.svelte$|' +
					'node_modules/(svelte-sonner|bits-ui|layercake|d3-[a-z]+|photoswipe|meilisearch|tailwind-merge|clsx|mode-watcher|@lucide/svelte|vaul-svelte)/',
				reachable: true
			}
		}
	],
	options: {
		doNotFollow: { path: 'node_modules' },
		exclude: { path: '\\.test\\.ts$' },
		// Runtime reachability only: type-only imports vanish at build.
		tsPreCompilationDeps: false,
		// Kit declares `$lib` in its generated tsconfig without a baseUrl, which
		// the tsconfig-paths resolver anchors to the wrong directory.
		tsConfig: { fileName: 'tsconfig.depcruise.json' },
		enhancedResolveOptions: {
			exportsFields: ['exports'],
			conditionNames: ['import', 'browser', 'default'],
			mainFields: ['module', 'browser', 'main']
		}
	}
};
