<script lang="ts" module>
	/** Body: the link is part of what you are reading — a value, a name, a
	 *  source. Underlined, so it is a link even where colour does not carry.
	 *  Quiet: the link is chrome around what you are reading — "see all", a
	 *  breadcrumb. Colour and position carry it; an underline would compete
	 *  with the content.
	 *  Heading: the link IS the heading. It keeps the heading's own colour and
	 *  weight — muting it would flatten the hierarchy the heading exists to
	 *  make — and earns its underline on hover. */
	export type LinkVariant = 'body' | 'quiet' | 'heading';
</script>

<script lang="ts">
	import type { Snippet } from 'svelte';
	import ExternalLinkIcon from '@lucide/svelte/icons/external-link';

	interface Props {
		/** Absent renders the children unwrapped — a name with nowhere to go is
		 *  still a name, and an <a> without an href is a link to everything that
		 *  inspects it and nothing to everyone who clicks it. */
		href?: string;
		/** Leaves the site: sets target and rel, and shows the trailing icon. */
		external?: boolean;
		/** Overrides the icon. Off for lists where every entry is external and
		 *  the icon repeats down the column saying nothing. */
		icon?: boolean;
		variant?: LinkVariant;
		/** Extra rel tokens with meaning of their own — `license`, `author`.
		 *  Appended; the safety tokens are not the caller's to choose. */
		rel?: string;
		/** Takes the plain left-click in-session; the href covers the rest. */
		onclick?: (e: MouseEvent) => void;
		title?: string;
		class?: string;
		children: Snippet;
	}

	let {
		href,
		external = false,
		icon,
		variant = 'body',
		rel,
		onclick,
		title,
		class: className = '',
		children
	}: Props = $props();

	let showIcon = $derived(icon ?? external);
	let relValue = $derived(
		external ? ['noopener', 'noreferrer', rel].filter(Boolean).join(' ') : rel
	);

	// pointer-events-auto because parts of the drawer sit over a canvas that
	// takes the pointer; rounded-xs so the focus ring follows the text box.
	const BASE =
		'pointer-events-auto rounded-xs transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring';
	const VARIANT: Record<LinkVariant, string> = {
		body: 'text-muted-foreground hover:text-foreground underline underline-offset-2',
		quiet: 'text-muted-foreground hover:text-foreground no-underline',
		heading: 'hover:underline underline-offset-2'
	};
</script>

{#if href}
	<a
		{href}
		{onclick}
		{title}
		target={external ? '_blank' : undefined}
		rel={relValue}
		class="{BASE} {VARIANT[variant]} {showIcon ? 'inline-flex items-center gap-1' : ''} {className}"
	>
		<!-- No whitespace between the text and the icon slot: inside an inline
		     anchor it renders as a trailing space, underlined, before whatever
		     punctuation follows the link. -->
		{@render children()}{#if showIcon}<ExternalLinkIcon class="size-3 shrink-0" />{/if}
	</a>
{:else}
	{@render children()}
{/if}
