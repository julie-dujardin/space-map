import js from '@eslint/js';
import ts from 'typescript-eslint';
import svelte from 'eslint-plugin-svelte';
import prettier from 'eslint-config-prettier';
import globals from 'globals';

/** Core code cannot depend on the host app. */
const HOST_APP = {
	group: ['$app/*', '$env/*', '$lib/paraglide/*', '$lib/components/*', 'svelte-sonner'],
	allowTypeImports: true,
	message: 'core code cannot depend on the host app — go through $lib/host'
};

/** Only the position module writes the place of a body. */
const PLACEMENT_WRITERS = {
	group: ['**/position/placement', '$lib/scene/position/placement'],
	importNames: ['setPlaced', 'setUnplaced', 'setOrbitCenter', 'setTrailAnchor'],
	message: 'Only lib/scene/position writes the place of a body: ask ctx.place().'
};

export default ts.config(
	js.configs.recommended,
	...ts.configs.recommended,
	...svelte.configs['flat/recommended'],
	prettier,
	...svelte.configs['flat/prettier'],
	{
		languageOptions: {
			globals: {
				...globals.browser,
				...globals.node
			}
		}
	},
	{
		files: ['**/*.svelte', '**/*.svelte.ts', '**/*.svelte.js'],
		languageOptions: {
			parserOptions: {
				parser: ts.parser
			}
		},
		rules: {
			// Crashes on Threlte's T.* components — plugin bug
			'svelte/no-navigation-without-resolve': 'off',
			'svelte/prefer-svelte-reactivity': 'off'
		}
	},
	{
		// A body with no known place has `position: null`. Nothing may stand a
		// coordinate in for it, and only the position module writes one.
		files: ['src/**'],
		ignores: ['src/lib/scene/position/**', '**/*.test.ts'],
		rules: {
			'no-restricted-syntax': [
				'error',
				{
					selector:
						":matches(LogicalExpression[operator='??'], LogicalExpression[operator='||']) > ArrayExpression.right[elements.length=3][elements.0.value=0][elements.1.value=0][elements.2.value=0]",
					message:
						'No origin fallback: a missing position is null, and the caller skips the body. Only the Solar System barycentre is at the origin (SSB_POSITION).'
				},
				{
					selector:
						":matches(LogicalExpression[operator='??'], LogicalExpression[operator='||']) > TSAsExpression.right > ArrayExpression[elements.length=3][elements.0.value=0][elements.1.value=0][elements.2.value=0]",
					message:
						'No origin fallback: a missing position is null, and the caller skips the body. Only the Solar System barycentre is at the origin (SSB_POSITION).'
				},
				{
					selector:
						"AssignmentExpression > MemberExpression.left[property.name='position']:not([object.property.name='style'])",
					message: 'Only lib/scene/position writes the place of a body (setPlaced / setUnplaced).'
				},
				{
					selector:
						"AssignmentExpression > MemberExpression.left[computed=true] > MemberExpression.object[property.name='position']",
					message: 'Only lib/scene/position writes the place of a body (setPlaced / setUnplaced).'
				},
				{
					selector:
						"AssignmentExpression > MemberExpression.left[computed=true] > TSNonNullExpression.object > MemberExpression[property.name='position']",
					message: 'Only lib/scene/position writes the place of a body (setPlaced / setUnplaced).'
				}
			],
			'@typescript-eslint/no-restricted-imports': ['error', { patterns: [PLACEMENT_WRITERS] }]
		}
	},
	{
		// The embeddable core stays host-agnostic; `pnpm check:core` enforces the
		// same rule transitively.
		files: ['src/lib/scene/**', 'src/lib/math/**', 'src/lib/fetch/**', 'src/sdk/**'],
		rules: {
			'@typescript-eslint/no-restricted-imports': [
				'error',
				{ patterns: [HOST_APP, PLACEMENT_WRITERS] }
			]
		}
	},
	{
		// The position module is the one place that imports the writers.
		files: ['src/lib/scene/position/**'],
		rules: {
			'@typescript-eslint/no-restricted-imports': ['error', { patterns: [HOST_APP] }]
		}
	},
	{
		ignores: ['build/', '.svelte-kit/', '.wrangler/', 'dist/', 'src/lib/paraglide/']
	}
);
