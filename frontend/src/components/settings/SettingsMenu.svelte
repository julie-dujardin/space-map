<script lang="ts">
	import ChevronDownIcon from '@lucide/svelte/icons/chevron-down';
	import * as m from '$lib/paraglide/messages.js';
	import { getLocale, locales, type Locale } from '$lib/paraglide/runtime.js';
	import { getSettings, type Clock, type Theme } from '$lib/state/settings.svelte';

	const settings = getSettings();

	// Native-name labels so users see their language in their language. Lookups
	// fall back to the locale tag if the entry is missing.
	const LOCALE_NAMES: Record<Locale, string> = {
		en: 'English',
		fr: 'Français',
		ja: '日本語',
		zh: '中文',
		ar: 'العربية',
		ru: 'Русский',
		pt: 'Português',
		de: 'Deutsch',
		it: 'Italiano',
		es: 'Español',
		he: 'עברית',
		pl: 'Polski'
	};

	const themeOptions: { value: Theme; label: () => string }[] = [
		{ value: 'auto', label: () => m.settings_auto() },
		{ value: 'dark', label: () => m.settings_theme_dark() },
		{ value: 'light', label: () => m.settings_theme_light() }
	];

	const clockOptions: { value: Clock; label: () => string }[] = [
		{ value: 'auto', label: () => m.settings_auto() },
		{ value: '24h', label: () => m.settings_clock_24h() },
		{ value: '12h', label: () => m.settings_clock_12h() }
	];

	const dateFormatOptions = [
		{ value: 'auto' as const, label: () => m.settings_dateformat_locale() },
		{ value: 'iso' as const, label: () => m.settings_dateformat_iso() }
	];

	function localeLabel(loc: Locale): string {
		return LOCALE_NAMES[loc] ?? loc;
	}

	// "auto" descriptions: what the resolved value is, and where it comes from.
	let resolvedClockLabel = $derived(
		settings.resolvedHour12 ? m.settings_clock_12h() : m.settings_clock_24h()
	);
	let resolvedThemeLabel = $derived(
		settings.resolvedTheme === 'dark' ? m.settings_theme_dark() : m.settings_theme_light()
	);
	// ISO date format implies 24h; lock the clock toggle so the UI matches the
	// behavior already enforced by the formatters.
	let clockLocked = $derived(settings.dateFormat === 'iso');
	let effectiveClock = $derived<Clock>(clockLocked ? '24h' : settings.clock);
</script>

<div class="flex flex-col">
	<header class="px-5 pt-5 pb-3">
		<h2 class="text-base font-semibold">{m.settings_title()}</h2>
		<p class="text-xs text-muted-foreground mt-0.5">{m.settings_stored_locally()}</p>
	</header>

	<div class="px-5 pb-5 flex flex-col gap-5 overflow-y-auto">
		<!-- DISPLAY -->
		<section class="flex flex-col gap-4">
			<h3 class="text-[10px] font-semibold tracking-[0.12em] text-muted-foreground uppercase">
				{m.settings_section_display()}
			</h3>

			<!-- Language -->
			<div class="flex flex-col gap-2">
				<div class="flex items-center justify-between gap-3">
					<div class="min-w-0">
						<div id="settings-language-label" class="text-sm font-medium">
							{m.settings_language()}
						</div>
					</div>
					<div class="relative shrink-0">
						<select
							class="appearance-none rounded-md border border-input bg-background pe-7 ps-2.5 py-1.5 text-sm
								cursor-pointer hover:bg-accent transition-colors
								focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
							aria-labelledby="settings-language-label"
							value={settings.language}
							onchange={(e) => {
								const v = (e.currentTarget as HTMLSelectElement).value;
								settings.setLanguage(v === 'auto' ? 'auto' : (v as Locale));
							}}
						>
							<option value="auto">{m.settings_auto()}</option>
							{#each locales as loc (loc)}
								<option value={loc}>{localeLabel(loc)}</option>
							{/each}
						</select>
						<ChevronDownIcon
							class="absolute end-1.5 top-1/2 -translate-y-1/2 size-3.5 opacity-50 pointer-events-none"
						/>
					</div>
				</div>
				{#if settings.language === 'auto'}
					<div class="flex items-center gap-1.5 text-xs text-muted-foreground">
						<span class="size-1.5 rounded-full bg-emerald-500" aria-hidden="true"></span>
						<span
							>{m.settings_auto_source({
								value: localeLabel(getLocale()),
								source: m.settings_source_browser({ tag: settings.browserLanguage })
							})}</span
						>
					</div>
				{/if}
			</div>

			<!-- Theme -->
			<div class="flex flex-col gap-2">
				<div class="flex items-center justify-between gap-3">
					<div class="min-w-0">
						<div class="text-sm font-medium">{m.settings_theme()}</div>
					</div>
					<div
						class="inline-flex shrink-0 rounded-md bg-muted p-0.5"
						role="radiogroup"
						aria-label={m.settings_theme()}
					>
						{#each themeOptions as opt (opt.value)}
							{@const active = settings.theme === opt.value}
							<button
								type="button"
								role="radio"
								aria-checked={active}
								class="px-2.5 py-1 text-xs font-medium rounded transition-colors cursor-pointer
									{active
									? 'bg-background text-foreground shadow-sm'
									: 'text-muted-foreground hover:text-foreground'}"
								onclick={() => settings.setTheme(opt.value)}
							>
								{opt.label()}
							</button>
						{/each}
					</div>
				</div>
				{#if settings.theme === 'auto'}
					<div class="flex items-center gap-1.5 text-xs text-muted-foreground">
						<span class="size-1.5 rounded-full bg-emerald-500" aria-hidden="true"></span>
						<span
							>{m.settings_auto_source({
								value: resolvedThemeLabel,
								source: m.settings_source_system()
							})}</span
						>
					</div>
				{/if}
			</div>
		</section>

		<!-- TIME -->
		<section class="flex flex-col gap-4">
			<h3 class="text-[10px] font-semibold tracking-[0.12em] text-muted-foreground uppercase">
				{m.settings_section_time()}
			</h3>

			<!-- Date format -->
			<div class="flex items-center justify-between gap-3">
				<div class="min-w-0">
					<div class="text-sm font-medium">{m.settings_dateformat()}</div>
				</div>
				<div
					class="inline-flex shrink-0 rounded-md bg-muted p-0.5"
					role="radiogroup"
					aria-label={m.settings_dateformat()}
				>
					{#each dateFormatOptions as opt (opt.value)}
						{@const active = settings.dateFormat === opt.value}
						<button
							type="button"
							role="radio"
							aria-checked={active}
							class="px-2.5 py-1 text-xs font-medium rounded transition-colors cursor-pointer
								{active
								? 'bg-background text-foreground shadow-sm'
								: 'text-muted-foreground hover:text-foreground'}"
							onclick={() => settings.setDateFormat(opt.value)}
						>
							{opt.label()}
						</button>
					{/each}
				</div>
			</div>

			<!-- Clock -->
			<div class="flex flex-col gap-2">
				<div class="flex items-center justify-between gap-3">
					<div class="min-w-0">
						<div class="text-sm font-medium">{m.settings_clock()}</div>
					</div>
					<div
						class="inline-flex shrink-0 rounded-md bg-muted p-0.5 transition-opacity {clockLocked
							? 'opacity-60'
							: ''}"
						role="radiogroup"
						aria-label={m.settings_clock()}
					>
						{#each clockOptions as opt (opt.value)}
							{@const active = effectiveClock === opt.value}
							<button
								type="button"
								role="radio"
								aria-checked={active}
								disabled={clockLocked}
								class="px-2.5 py-1 text-xs font-medium rounded transition-colors
									{clockLocked ? 'cursor-not-allowed' : 'cursor-pointer'}
									{active
									? 'bg-background text-foreground shadow-sm'
									: 'text-muted-foreground hover:text-foreground'}"
								onclick={() => settings.setClock(opt.value)}
							>
								{opt.label()}
							</button>
						{/each}
					</div>
				</div>
				{#if clockLocked}
					<div class="flex items-center gap-1.5 text-xs text-muted-foreground">
						<span class="size-1.5 rounded-full bg-emerald-500" aria-hidden="true"></span>
						<span
							>{m.settings_auto_source({
								value: m.settings_clock_24h(),
								source: m.settings_source_iso()
							})}</span
						>
					</div>
				{:else if settings.clock === 'auto'}
					<div class="flex items-center gap-1.5 text-xs text-muted-foreground">
						<span class="size-1.5 rounded-full bg-emerald-500" aria-hidden="true"></span>
						<span
							>{m.settings_auto_source({
								value: resolvedClockLabel,
								source: m.settings_source_locale()
							})}</span
						>
					</div>
				{/if}
			</div>
		</section>

		<!-- DEVELOPER -->
		<section class="flex flex-col gap-4">
			<h3 class="text-[10px] font-semibold tracking-[0.12em] text-muted-foreground uppercase">
				{m.settings_section_developer()}
			</h3>

			<label class="flex items-center justify-between gap-3 cursor-pointer">
				<div class="min-w-0">
					<div class="text-sm font-medium">{m.settings_debug_info()}</div>
					<div class="text-xs text-muted-foreground mt-0.5">{m.settings_debug_info_desc()}</div>
				</div>
				<button
					type="button"
					role="switch"
					aria-checked={settings.showDebugInfo}
					aria-label={m.settings_debug_info()}
					class="relative inline-flex shrink-0 h-5 w-9 items-center rounded-full transition-colors cursor-pointer
						focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50
						{settings.showDebugInfo ? 'bg-primary' : 'bg-muted'}"
					onclick={() => settings.setShowDebugInfo(!settings.showDebugInfo)}
				>
					<span
						class="inline-block size-4 rounded-full bg-background shadow transition-transform
							{settings.showDebugInfo ? 'translate-x-4' : 'translate-x-0.5'}"
					></span>
				</button>
			</label>
		</section>
	</div>
</div>
