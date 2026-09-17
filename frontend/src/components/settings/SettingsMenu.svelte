<script lang="ts">
	import ChevronDownIcon from '@lucide/svelte/icons/chevron-down';
	import type { Snippet } from 'svelte';
	import * as m from '$lib/paraglide/messages.js';
	import { getLocale, locales, type Locale } from '$lib/paraglide/runtime.js';
	import {
		getSettings,
		type Clock,
		type DateFormatChoice,
		type PanoramaGyro,
		type ReducedMotion,
		type Theme
	} from '$lib/state/settings.svelte';
	import { gyroAvailability } from '$lib/panorama/gyro';
	import {
		resolveAtmosphereTier,
		type AtmosphereQualityTier
	} from '$lib/scene/objects/surface/atmosphere-quality';
	import { recalibrateAtmosphere } from '$lib/scene/perf/atmosphere-calibration';
	import { switchLanguage } from '$lib/state/language';

	/** Graphics and the debug overlay only change what the 3D scene draws, so the
	 *  map alone carries them; the date formatters are reached from anything that
	 *  dates what it shows. The document pages carry the display settings and
	 *  nothing else. */
	export type SettingsScope = 'map' | 'panorama' | 'page';

	interface Props {
		scope?: SettingsScope;
	}

	let { scope = 'map' }: Props = $props();

	const showTime = $derived(scope !== 'page');
	const showScene = $derived(scope === 'map');

	const settings = getSettings();

	/** Every segmented row selects one of these. */
	type SegmentedValue = Theme | Clock | ReducedMotion | DateFormatChoice | PanoramaGyro;
	interface SegmentedOption {
		value: SegmentedValue;
		label: () => string;
	}

	let recalibrating = $state(false);

	async function rerunBenchmark(): Promise<void> {
		if (recalibrating) return;
		recalibrating = true;
		try {
			await recalibrateAtmosphere();
		} finally {
			recalibrating = false;
		}
	}

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

	const gyroOptions: { value: PanoramaGyro; label: () => string }[] = [
		{ value: 'auto', label: () => m.settings_auto() },
		{ value: 'on', label: () => m.settings_reduced_motion_on() },
		{ value: 'off', label: () => m.settings_reduced_motion_off() }
	];

	/** Why the orientation sensor is out of reach, where it is; the row is then
	 *  shown locked with this under it. */
	const gyroUnavailable = $derived.by(() => {
		const availability = gyroAvailability();
		if (availability === 'available') return undefined;
		return availability === 'insecure' ? m.panorama_gyro_insecure() : m.panorama_gyro_no_sensor();
	});

	const fullscreenSupported = typeof document !== 'undefined' && document.fullscreenEnabled;
	/** The document pages scroll; only the two full-screen views offer it. */
	const showFullscreen = $derived(scope !== 'page' && fullscreenSupported);
	let fullscreen = $state(false);

	$effect(() => {
		const sync = () => (fullscreen = document.fullscreenElement !== null);
		sync();
		document.addEventListener('fullscreenchange', sync);
		return () => document.removeEventListener('fullscreenchange', sync);
	});

	/** The whole document, so the chrome goes with the view. A refusal leaves
	 *  the switch where the listener last put it. */
	async function toggleFullscreen(): Promise<void> {
		try {
			if (document.fullscreenElement) await document.exitFullscreen();
			else await document.documentElement.requestFullscreen();
		} catch {
			// Denied or unavailable; `fullscreenchange` never fires.
		}
	}

	const reducedMotionOptions: { value: ReducedMotion; label: () => string }[] = [
		{ value: 'auto', label: () => m.settings_auto() },
		{ value: 'off', label: () => m.settings_reduced_motion_off() },
		{ value: 'on', label: () => m.settings_reduced_motion_on() }
	];

	const TIER_LABELS: Record<'low' | 'medium' | 'high' | 'ultra', () => string> = {
		low: () => m.settings_quality_low(),
		medium: () => m.settings_quality_medium(),
		high: () => m.settings_quality_high(),
		ultra: () => m.settings_quality_ultra()
	};

	const atmoQualityOptions: { value: AtmosphereQualityTier; label: () => string }[] = [
		{ value: 'auto', label: () => m.settings_auto() },
		{ value: 'low', label: TIER_LABELS.low },
		{ value: 'medium', label: TIER_LABELS.medium },
		{ value: 'high', label: TIER_LABELS.high },
		{ value: 'ultra', label: TIER_LABELS.ultra }
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
	let resolvedReducedMotionLabel = $derived(
		settings.resolvedReducedMotion
			? m.settings_reduced_motion_on()
			: m.settings_reduced_motion_off()
	);
	let resolvedAtmoQualityLabel = $derived(
		TIER_LABELS[resolveAtmosphereTier(settings.atmosphereQuality)]()
	);
	// ISO date format implies 24h; lock the clock toggle so the UI matches the
	// behavior already enforced by the formatters.
	let clockLocked = $derived(settings.dateFormat === 'iso');
	let effectiveClock = $derived<Clock>(clockLocked ? '24h' : settings.clock);
</script>

<!-- `locked` given at all marks the row as lockable: only those animate their
     opacity and carry a `disabled` state. -->
{#snippet segmented(
	label: string,
	options: SegmentedOption[],
	value: SegmentedValue,
	set: (value: SegmentedValue) => void,
	locked?: boolean
)}
	<div class="flex items-center justify-between gap-3">
		<div class="min-w-0">
			<div class="text-sm font-medium">{label}</div>
		</div>
		<div
			class="inline-flex shrink-0 rounded-md bg-muted p-0.5 {locked === undefined
				? ''
				: 'transition-opacity'} {locked ? 'opacity-60' : ''}"
			role="radiogroup"
			aria-label={label}
		>
			{#each options as opt (opt.value)}
				{@const active = value === opt.value}
				<button
					type="button"
					role="radio"
					aria-checked={active}
					disabled={locked}
					class="px-2.5 py-1 text-xs font-medium rounded transition-colors
						{locked ? 'cursor-not-allowed' : 'cursor-pointer'}
						{active
						? 'bg-background text-foreground shadow-sm'
						: 'text-muted-foreground hover:text-foreground'}"
					onclick={() => set(opt.value)}
				>
					{opt.label()}
				</button>
			{/each}
		</div>
	</div>
{/snippet}

{#snippet autoSource(value: string, source: string, trailing?: Snippet)}
	<div class="flex items-center gap-1.5 text-xs text-muted-foreground">
		<span class="size-1.5 rounded-full bg-emerald-500" aria-hidden="true"></span>
		<span>{m.settings_auto_source({ value, source })}</span>
		{@render trailing?.()}
	</div>
{/snippet}

{#snippet recalibrateButton()}
	<button
		type="button"
		class="ms-auto shrink-0 underline underline-offset-2 hover:text-foreground
			disabled:opacity-60 disabled:no-underline transition-colors
			focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded-sm"
		disabled={recalibrating}
		onclick={rerunBenchmark}
	>
		{recalibrating ? m.settings_recalibrate_running() : m.settings_recalibrate()}
	</button>
{/snippet}

<div class="flex min-h-0 flex-col">
	<header class="px-5 pt-5 pb-3">
		<h2 class="text-base font-semibold">{m.settings_title()}</h2>
		<p class="text-xs text-muted-foreground mt-0.5">{m.settings_stored_locally()}</p>
	</header>

	<div class="px-5 pb-5 flex min-h-0 flex-col gap-5 overflow-y-auto">
		<section class="flex flex-col gap-4">
			<h3 class="text-[10px] font-semibold tracking-[0.12em] text-muted-foreground uppercase">
				{m.settings_section_display()}
			</h3>

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
								focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
							aria-labelledby="settings-language-label"
							value={settings.language}
							onchange={(e) => {
								const v = (e.currentTarget as HTMLSelectElement).value;
								switchLanguage(v === 'auto' ? 'auto' : (v as Locale));
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
					{@render autoSource(
						localeLabel(getLocale()),
						m.settings_source_browser({ tag: settings.browserLanguage })
					)}
				{/if}
			</div>

			<div class="flex flex-col gap-2">
				{@render segmented(m.settings_theme(), themeOptions, settings.theme, (v) =>
					settings.setTheme(v as Theme)
				)}
				{#if settings.theme === 'auto'}
					{@render autoSource(resolvedThemeLabel, m.settings_source_system())}
				{/if}
			</div>

			<div class="flex flex-col gap-2">
				{@render segmented(
					m.settings_reduced_motion(),
					reducedMotionOptions,
					settings.reducedMotion,
					(v) => settings.setReducedMotion(v as ReducedMotion)
				)}
				{#if settings.reducedMotion === 'auto'}
					{@render autoSource(resolvedReducedMotionLabel, m.settings_source_system())}
				{/if}
			</div>

			{#if scope === 'panorama'}
				<div class="flex flex-col gap-2">
					{@render segmented(
						m.panorama_gyro(),
						gyroOptions,
						settings.panoramaGyro,
						(v) => settings.setPanoramaGyro(v as PanoramaGyro),
						gyroUnavailable !== undefined
					)}
					{#if gyroUnavailable}
						<p class="text-xs text-muted-foreground">{gyroUnavailable}</p>
					{:else if settings.panoramaGyro === 'auto' && settings.resolvedReducedMotion}
						{@render autoSource(
							m.settings_reduced_motion_off(),
							m.settings_source_reduced_motion()
						)}
					{:else}
						<p class="text-xs text-muted-foreground">{m.panorama_gyro_hint()}</p>
					{/if}
				</div>
			{/if}

			{#if showFullscreen}
				<label class="flex cursor-pointer items-center justify-between gap-3">
					<div class="min-w-0">
						<div class="text-sm font-medium">{m.settings_fullscreen()}</div>
					</div>
					<button
						type="button"
						role="switch"
						aria-checked={fullscreen}
						aria-label={m.settings_fullscreen()}
						class="relative inline-flex shrink-0 h-5 w-9 items-center rounded-full transition-colors cursor-pointer
								focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring
								{fullscreen ? 'bg-primary' : 'bg-muted'}"
						onclick={() => void toggleFullscreen()}
					>
						<span
							class="inline-block size-4 rounded-full bg-background shadow transition-transform
									{fullscreen ? 'translate-x-4' : 'translate-x-0.5'}"
						></span>
					</button>
				</label>
			{/if}
		</section>

		{#if showTime}
			<section class="flex flex-col gap-4">
				<h3 class="text-[10px] font-semibold tracking-[0.12em] text-muted-foreground uppercase">
					{m.settings_section_time()}
				</h3>

				{@render segmented(m.settings_dateformat(), dateFormatOptions, settings.dateFormat, (v) =>
					settings.setDateFormat(v as DateFormatChoice)
				)}

				<div class="flex flex-col gap-2">
					{@render segmented(
						m.settings_clock(),
						clockOptions,
						effectiveClock,
						(v) => settings.setClock(v as Clock),
						clockLocked
					)}
					{#if clockLocked}
						{@render autoSource(m.settings_clock_24h(), m.settings_source_iso())}
					{:else if settings.clock === 'auto'}
						{@render autoSource(resolvedClockLabel, m.settings_source_locale())}
					{/if}
				</div>
			</section>
		{/if}

		{#if showScene}
			<section class="flex flex-col gap-4">
				<h3 class="text-[10px] font-semibold tracking-[0.12em] text-muted-foreground uppercase">
					{m.settings_section_graphics()}
				</h3>

				<div class="flex flex-col gap-2">
					<div class="flex items-center justify-between gap-3">
						<div class="min-w-0">
							<div id="settings-atmo-quality-label" class="text-sm font-medium">
								{m.settings_atmosphere_quality()}
							</div>
						</div>
						<div class="relative shrink-0">
							<select
								class="appearance-none rounded-md border border-input bg-background pe-7 ps-2.5 py-1.5 text-sm
										cursor-pointer hover:bg-accent transition-colors
										focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
								aria-labelledby="settings-atmo-quality-label"
								value={settings.atmosphereQuality}
								onchange={(e) =>
									settings.setAtmosphereQuality(
										(e.currentTarget as HTMLSelectElement).value as AtmosphereQualityTier
									)}
							>
								{#each atmoQualityOptions as opt (opt.value)}
									<option value={opt.value}>{opt.label()}</option>
								{/each}
							</select>
							<ChevronDownIcon
								class="absolute end-1.5 top-1/2 -translate-y-1/2 size-3.5 opacity-50 pointer-events-none"
							/>
						</div>
					</div>
					{#if settings.atmosphereQuality === 'auto'}
						{@render autoSource(
							resolvedAtmoQualityLabel,
							settings.atmosphereAutoTier
								? m.settings_source_perf()
								: settings.atmosphereCalibration
									? m.settings_source_benchmark()
									: m.settings_source_device(),
							recalibrateButton
						)}
					{/if}
				</div>
			</section>

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
								focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring
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
		{/if}
	</div>
</div>
