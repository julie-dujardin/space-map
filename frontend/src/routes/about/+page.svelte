<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import SitePage from '../../components/nav/SitePage.svelte';
	import { Skeleton } from '$lib/components/ui/skeleton/index.js';
	import { locales } from '$lib/paraglide/runtime';
	import { streamed } from '$lib/state/streamed.svelte';
	import { groupHref } from '$lib/state/page-href';
	import { categoryLabel } from '$lib/format/group';
	import {
		CAT_ASTEROIDS,
		CAT_COMETS,
		CAT_DEBRIS,
		CAT_DWARF_PLANETS,
		CAT_MOONS,
		CAT_PLANETS,
		CAT_RING_SYSTEMS,
		CAT_SPACECRAFT,
		CAT_STRUCTURE_ACTIVITY,
		CAT_SURFACE_FEATURES
	} from '$lib/fetch/groups/registry';
	import { roundCount, shortCount, type AboutFigures } from '$lib/about/about-figures';

	interface Props {
		data: { figures: Promise<AboutFigures> };
	}

	let { data }: Props = $props();
	const figures = streamed<AboutFigures>(() => data.figures);

	const asOf = $derived(
		figures.value &&
			new Date(figures.value.generatedAt).toLocaleDateString('en', {
				month: 'long',
				year: 'numeric',
				timeZone: 'UTC'
			})
	);

	// The text is the README's, in English only.
	// Prettier strips the space from a bare comma between links.
	const SEP = ', ';
	const SOURCES: {
		type: string;
		category: string;
		count: (f: AboutFigures) => number;
		links: [string, string][];
	}[] = [
		{
			type: 'Planets',
			category: CAT_PLANETS,
			count: (f) => f.planets,
			links: [['NASA SPICE kernels (NAIF)', 'https://naif.jpl.nasa.gov/naif/']]
		},
		{
			type: 'Dwarf planets',
			category: CAT_DWARF_PLANETS,
			count: (f) => f.dwarfPlanets,
			links: [['NASA JPL Horizons', 'https://ssd.jpl.nasa.gov/horizons/']]
		},
		{
			type: 'Moons',
			category: CAT_MOONS,
			count: (f) => f.moons,
			links: [
				['NASA JPL Horizons', 'https://ssd.jpl.nasa.gov/horizons/'],
				['Small-Body Database', 'https://ssd.jpl.nasa.gov/tools/sbdb_lookup.html'],
				['Natural Satellites Data Base (SAI/IMCCE)', 'https://www.sai.msu.ru/neb/nss/'],
				["Johnston's Archive", 'https://www.johnstonsarchive.net/astro/asteroidmoons.html']
			]
		},
		{
			type: 'Asteroids',
			category: CAT_ASTEROIDS,
			count: (f) => f.asteroids,
			links: [['Small-Body Database', 'https://ssd.jpl.nasa.gov/tools/sbdb_lookup.html']]
		},
		{
			type: 'Comets',
			category: CAT_COMETS,
			count: (f) => f.comets,
			links: [['Small-Body Database', 'https://ssd.jpl.nasa.gov/tools/sbdb_lookup.html']]
		},
		{
			type: 'Spacecraft',
			category: CAT_SPACECRAFT,
			count: (f) => f.spacecraft,
			links: [
				['CelesTrak', 'https://celestrak.org/'],
				['Space-Track', 'https://www.space-track.org/'],
				['NASA JPL Horizons', 'https://ssd.jpl.nasa.gov/horizons/'],
				['NAIF', 'https://naif.jpl.nasa.gov/naif/'],
				['PDS', 'https://pds.nasa.gov/'],
				['ESA SPICE Service', 'https://www.cosmos.esa.int/web/spice'],
				['JAXA DARTS', 'https://darts.isas.jaxa.jp/']
			]
		},
		{
			type: 'Satellite debris',
			category: CAT_DEBRIS,
			count: (f) => f.debris,
			links: [
				['CelesTrak', 'https://celestrak.org/'],
				['Space-Track', 'https://www.space-track.org/']
			]
		},
		{
			type: 'Surface features',
			category: CAT_SURFACE_FEATURES,
			count: (f) => f.surfaceFeatures,
			links: [
				[
					'Gazetteer of Planetary Nomenclature (IAU/USGS/NASA)',
					'https://planetarynames.wr.usgs.gov/'
				]
			]
		}
	];
</script>

<svelte:head>
	<title>{m.nav_about()} - {m.page_title()}</title>
</svelte:head>

<!-- A figure of the payload, a block while it loads, a dash if it fails. -->
{#snippet num(value: number | string | undefined | false)}
	{#if value !== undefined && value !== false}{typeof value === 'number'
			? shortCount(value)
			: value}{:else if figures.error}–{:else}<Skeleton
			class="inline-block h-3 w-8 align-baseline"
		/>{/if}
{/snippet}

{#snippet out(href: string, label: string)}
	<a {href} target="_blank" rel="noopener noreferrer">{label}</a>
{/snippet}

<SitePage current="about" title={m.nav_about()}>
	<!-- The README's own words, so the page is English in every locale. -->
	<div
		lang="en"
		dir="ltr"
		class="max-w-prose text-sm leading-relaxed text-muted-foreground [&_a]:text-foreground [&_a]:underline [&_a]:decoration-border [&_a]:underline-offset-2 [&_a:hover]:decoration-current [&_h2]:mt-10 [&_h2]:mb-2 [&_h2]:text-base [&_h2]:font-semibold [&_h2]:text-foreground [&_h3]:mt-6 [&_h3]:mb-2 [&_h3]:font-semibold [&_h3]:text-foreground [&_li]:mt-1.5 [&_p]:mt-3 [&_ul]:list-disc [&_ul]:ps-5"
	>
		<p class="text-base text-foreground">
			Space Map is a real-time, real-scale, fully continuous map of the solar system, mapping {@render num(
				figures.value?.objects
			)} objects and {@render num(figures.value?.surfaceFeatures)} surface features as of {@render num(
				asOf
			)}.
		</p>

		<h2>Features</h2>
		<p>
			Space Map computes positions at any date, using orbital elements from NASA, ESA, JAXA, and the
			US Space Force:
		</p>
		<table class="mt-4 w-full text-start">
			<thead class="text-xs font-semibold uppercase tracking-wider text-muted-subtle">
				<tr class="border-b border-border">
					<th class="py-1.5 pe-4 text-start font-semibold">Type</th>
					<th class="py-1.5 pe-4 text-end font-semibold">Count</th>
					<th class="py-1.5 text-start font-semibold">Source</th>
				</tr>
			</thead>
			<tbody>
				{#each SOURCES as row (row.type)}
					<tr class="border-b border-border/50 align-baseline">
						<td class="py-1.5 pe-4 text-foreground"
							><a href={groupHref(row.category, categoryLabel(row.category))}>{row.type}</a></td
						>
						<td class="py-1.5 pe-4 text-end tabular-nums"
							>{@render num(figures.value && row.count(figures.value))}</td
						>
						<td class="py-1.5">
							{#each row.links as [label, href], i (href)}{#if i > 0}{SEP}{/if}{@render out(
									href,
									label
								)}{/each}
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
		<p>See the full list at <a href="/about/data">spacemap.co/about/data</a></p>
		<p>
			Each of these is displayed at its current position, and shown at its real size (when known).
			Click any object to focus it.
		</p>
		<ul>
			<li>Time control: Speed up or reverse time, go to any date.</li>
			<li>
				<a href="/nav/naif-399/naif-499?at=2029-12-20T12:28:52.605Z,53.98086,8.01888,26.955"
					>Navigation to any object</a
				>, with transfer windows, gravity assists, and brachistochrone trajectories, real &
				fictional spacecraft, and
				<a
					href="/nav/naif-399/naif-699?at=2029-12-20T12:28:04.084Z,25.07064,-78.08883,0.050851&tm=custom&talt=221099&tinc=9&route=balanced"
					>end-to-end directions</a
				>.
			</li>
			<li>
				{@render num(figures.value?.panoramas)} Streetview-like
				<a href="/view">ground level panoramas</a> on Mars, the Moon, Titan, and Venus.
			</li>
			<li>
				Search: Text search & advanced filters, infinite scroll - it's 2026, time to doomscroll
				<a href="/b/399?f=pha">potentially hazardous asteroids</a>.
			</li>
			<li>
				Detailed facts about each object & place: mass & size, classification, date of discovery,
				source datasets, and more.
			</li>
			<li>
				Collections: See all <a href="/g/const-starlink">Starlink</a>,
				<a href="/g/const-gps">GPS</a>, <a href="/g/class-GEO">Geostationary</a> satellites, the
				<a href="/g/class-TJN/Jupiter%20Trojan?at=now,34.60900,58.08478,131.68"
					>Jupiter Trojan asteroids</a
				>,
				<a href="/g/class-HYP/Hyperbolic%20Comet?at=now,20.47956,140.22461,42.430"
					>hyperbolic comets</a
				>, <a href="/g/ft-crater">Craters</a>, etc.
			</li>
		</ul>

		<h3>Natural bodies</h3>
		<ul>
			<li>
				<a
					href="/e/25544/International%20Space%20Station?at=2026-07-08T22:35:21.390Z,12.53355,29.96924,1.0570e-8"
					>Data driven atmospheric rendering</a
				>
				down to
				<a
					href="/p/100265984/Mars%20Science%20Laboratory?at=2026-07-28T14:17:41.132Z,-42.90792,-107.14203,4.6896e-10"
					>ground level</a
				>.
			</li>
			<li>
				High-resolution streamed textures & topography for all planets, {@render num(
					figures.value?.texturedMoons
				)} moons, and {@render num(figures.value?.texturedMinorBodies)} minor bodies. Mars: 5m per pixel,
				the Moon: 100m per pixel, Mercury: 166m per pixel, Lander areas: up to 0.25m per pixel.
			</li>
			<li>
				3D models for {@render num(figures.value?.shapedBodies)}
				<a href="/s/20101955/101955%20Bennu?at=now,-0.99190,142.87246,4.7560e-8">asteroids</a>,
				<a href="/s/1000012/67P%2FChuryumov%E2%80%93Gerasimenko?at=now,48.95132,65.96561,3.7911e-7"
					>comets</a
				>, and <a href="/b/618/Pan?at=now,20.79260,41.75821,0.0000048744">moons</a>; colors for {@render num(
					figures.value?.colouredBodies
				)} small bodies from {@render out(
					'https://github.com/Askaniy/TrueColorTools',
					'TrueColorTools'
				)}.
			</li>
			<li>
				System-scale lighting with
				<a
					href="/b/499/f/2757/Ius%20Chasma?at=2026-09-04T13:54:43.410Z,-23.46737,133.08964,0.0000038200"
					>sunsets</a
				>,
				<a href="/b/399/Earth?at=2027-08-02T10:00:00.000Z,28.17996,30.91585,0.00082651"
					>accurate eclipses</a
				>,
				<a href="/b/301/f/6163/Tycho?at=2026-11-02T01:24:12.715Z,-88.15920,31.68708,0.000012024"
					>self-shadowing</a
				>,
				<a href="/b/699/Saturn?at=2020-11-17T22:58:33.684Z,11.90051,-20.83658,0.010587">ringshine</a
				>, and
				<a href="/b/401/Phobos?at=2026-11-01T21:27:18.499Z,21.10221,-22.17875,0.0000022496"
					>planetshine</a
				>.
			</li>
			<li>
				Rich data on
				<a href={groupHref(CAT_RING_SYSTEMS, categoryLabel(CAT_RING_SYSTEMS))}
					>planetary ring systems</a
				>
				from {@render out('https://pds-rings.seti.org/saturn/saturn_rings_table.html', 'NASA PDS')},
				the
				<a href={groupHref(CAT_STRUCTURE_ACTIVITY, categoryLabel(CAT_STRUCTURE_ACTIVITY))}
					>atmospheres & interiors</a
				>
				of 21 planets and moons from 100+ papers.
			</li>
		</ul>

		<h3>Probes</h3>
		<ul>
			<li>
				Historical positions for Earth satellites & probes from
				<a href="/b/399/Earth?at=1959-06-30T23:46:01.557Z,42.14541,151.20487,0.0023256">1959</a>, in
				flight and on the ground. Coverage is limited for early & non-US/EU/JA spacecraft.
			</li>
			<li>Historical attitude & orientation for 26 probes and 5 landers.</li>
			<li>
				Over {@render num(figures.value && String(roundCount(figures.value.craftModels)))} spacecraft
				with 3D models:
				<a href="/e/25544/International%20Space%20Station?at=now,35.24905,-17.25253,1.3451e-8"
					>ISS</a
				>,
				<a href="/e/20580/Hubble%20Space%20Telescope?at=now,19.83363,-95.19624,1.9914e-9">Hubble</a
				>,
				<a href="/p/115347456/James%20Webb%20Space%20Telescope?at=now,54.61394,115.76731,1.9039e-9"
					>James Webb</a
				>,
				<a href="/p/107159552/Juno?at=2022-08-17T15:29:50.557Z,64.88818,-21.50912,1.0027e-9">Juno</a
				>,
				<a href="/p/88592384/Cassini?at=2013-07-09T06:37:40.977Z,63.94176,-121.21263,2.1247e-9"
					>Cassini</a
				>,
				<a
					href="/p/104804352/New%20Horizons?at=2015-07-14T11:30:51.731Z,45.06167,34.07062,8.5505e-10"
					>New Horizons</a
				>,
				<a href="/p/49000448/Voyager%202?at=1989-08-25T02:58:36.961Z,76.62626,0.66449,1.4615e-9"
					>Voyager 2</a
				>.
			</li>
		</ul>

		<h3>More</h3>
		<ul>
			<li>
				<a href="/compare">Compare any object that renders on the map</a> in a side-by-side, to-scale
				comparison with everyday objects.
			</li>
			<li>Deep links: Easily share what you're looking at.</li>
			<li>
				Images from Wikimedia Commons for {@render num(figures.value?.images)} objects, descriptions from
				Wikipedia for {@render num(figures.value?.descriptions)}. Metadata from Wikidata and {@render out(
					'https://planet4589.org/space/gcat/index.html',
					"Jonathan C. McDowell's GCAT"
				)}.
			</li>
			<li>
				Localization: Full localization in {locales.length} languages, with content from Wikipedia. UI
				elements were localized by Claude Opus & Fable.
			</li>
			<li>Credits & sources: see full attributions in the <a href="/credits">credits page</a>.</li>
			<li>Performance: Load a solar system faster than your bank can show you your balance.</li>
			<li>Easter eggs: I won't spoil them for you.</li>
		</ul>

		<h3>SDK</h3>
		<p>
			SpaceMap can be easily integrated into your websites with the {@render out(
				'https://www.npmjs.com/package/spacemap',
				'SpaceMap SDK'
			)}.
		</p>
		<ul>
			<li>Use 3D & 2D maps and surface panoramas.</li>
			<li>Full control over what's rendered, camera focus & position.</li>
			<li>Draw on the map, and add in your own content.</li>
			<li>
				Check out {@render out('https://spaceguesser.com/', 'SpaceGuesser.com')} for examples.
			</li>
		</ul>
	</div>
</SitePage>
