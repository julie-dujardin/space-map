import js from '@eslint/js';
import ts from 'typescript-eslint';
import svelte from 'eslint-plugin-svelte';
import prettier from 'eslint-config-prettier';
import globals from 'globals';

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
		// The embeddable core stays host-agnostic; `pnpm check:core` enforces the
		// same rule transitively.
		files: ['src/lib/scene/**', 'src/lib/math/**', 'src/lib/fetch/**'],
		rules: {
			'@typescript-eslint/no-restricted-imports': [
				'error',
				{
					patterns: [
						{
							group: ['$app/*', '$env/*', '$lib/paraglide/*', '$lib/components/*', 'svelte-sonner'],
							allowTypeImports: true,
							message: 'core code cannot depend on the host app — go through $lib/host'
						}
					]
				}
			]
		}
	},
	{
		ignores: ['build/', '.svelte-kit/', '.wrangler/', 'dist/', 'src/lib/paraglide/']
	}
);
