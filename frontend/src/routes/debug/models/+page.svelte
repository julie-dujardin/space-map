<!--
  Dev tool: every curated model bundle beside the objects it is attached to, so
  a mesh landing on the wrong craft is visible at a glance. One shared WebGL
  context renders the contact-sheet thumbnails and, when a bundle is maximized,
  drives a live orbit viewer.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import {
		ACESFilmicToneMapping,
		AmbientLight,
		Box3,
		DirectionalLight,
		Group,
		type Object3D,
		PerspectiveCamera,
		Scene,
		SRGBColorSpace,
		Sphere,
		WebGLRenderer
	} from 'three';
	import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
	import {
		disposeGltf,
		fetchBundleMeta,
		modelLoader,
		modelTierCredit,
		shapeModelCredit,
		type ModelBundleMeta,
		type ModelTier,
		type ModelTierExport
	} from '$lib/scene/objects/body/model';
	import { makeEnvMap } from '$lib/scene/lighting';
	import { frameMapQuaternion } from '$lib/math/orientation';
	import { fetchMetadata } from '$lib/fetch/metadata';
	import { versionedUrl } from '$lib/fetch/data-base';
	import { bodyHref } from '$lib/state/url';

	interface IndexObject {
		id: string;
		name: string;
		type: string;
	}
	interface IndexBundle {
		kind?: string;
		tiers?: string[];
		scale_meters?: number | null;
		body_span_ratio?: number | null;
		objects: IndexObject[];
	}
	/** Sidecar fields the scene ignores but a credit line needs. */
	type TierExport = ModelTierExport & { catalog?: string };
	interface BundleMeta extends ModelBundleMeta {
		provenance?: string;
		archive?: string;
		exports: { high: TierExport; low?: TierExport };
	}
	interface Credit {
		tiers: string;
		name: string;
		url: string;
		license?: string;
		catalog?: string;
	}
	interface Bundle extends IndexBundle {
		slug: string;
		/** No attached object's name shares a word with the slug. Catches a mesh
		 *  on an unrelated craft (ACE's, on Ramses); blind to a wrong member of
		 *  the right family (a Viking orbiter under `viking-lander`), which only
		 *  the thumbnail shows. */
		suspect: boolean;
	}

	// Square thumbnails, rendered once each and blitted into a 2D canvas so the
	// sheet costs one WebGL context rather than one per card.
	const THUMB = 320;
	const CRAFT_ENV_INTENSITY = 0.35;

	let bundles = $state<Bundle[]>([]);
	let error = $state<string | null>(null);
	let query = $state('');
	let kindFilter = $state<'all' | 'craft' | 'shape'>('craft');
	let onlyUnattached = $state(false);
	let onlySuspect = $state(false);
	let selected = $state<Bundle | null>(null);
	let spin = $state(true);
	/** Per-bundle sidecars, keyed by slug — where the credits live. */
	let metas = $state<Record<string, BundleMeta>>({});

	const shown = $derived(
		bundles.filter((b) => {
			const isShape = b.kind === 'shape_model';
			if (kindFilter === 'craft' && isShape) return false;
			if (kindFilter === 'shape' && !isShape) return false;
			if (onlyUnattached && b.objects.length > 0) return false;
			if (onlySuspect && !b.suspect) return false;
			const q = query.trim().toLowerCase();
			if (!q) return true;
			return b.slug.includes(q) || b.objects.some((o) => o.name?.toLowerCase().includes(q));
		})
	);

	function words(s: string): Set<string> {
		return new Set(
			s
				.toLowerCase()
				.split(/[^a-z0-9]+/)
				.filter((w) => w.length > 2)
		);
	}

	function isSuspect(slug: string, objects: IndexObject[]): boolean {
		// An unnamed object can't disagree with the slug, so it neither flags the
		// bundle nor vouches for it.
		const named = objects.filter((o) => o.name);
		if (named.length === 0) return false;
		const slugWords = words(slug);
		return named.every((o) => {
			const shared = [...words(o.name)].filter((w) => slugWords.has(w));
			return shared.length === 0;
		});
	}

	// --- credits -------------------------------------------------------------

	/** index.json carries no attribution, so a bundle can only be credited once
	 *  its sidecar lands — fetched as the card scrolls in, beside the thumbnail. */
	async function ensureMeta(slug: string): Promise<BundleMeta> {
		const meta = (await fetchBundleMeta(slug)) as BundleMeta;
		metas[slug] = meta;
		return meta;
	}

	/** Who a tier's GLB belongs to, by the same rules the scene credits it under:
	 *  a shape model's top-level credit covers the bundle, while a craft's tiers
	 *  can name different catalogues (Cassini's high is ESA's, its low NASA's). */
	function tierCredit(meta: BundleMeta | undefined, tier: string): Credit | null {
		if (!meta?.exports?.high) return null;
		const c =
			meta.kind === 'shape_model'
				? shapeModelCredit(meta)
				: modelTierCredit(meta, tier as ModelTier);
		return { tiers: tier, ...c, catalog: meta.exports[tier as ModelTier]?.catalog };
	}

	/** One line per distinct credit, merging the tiers that share one. */
	function bundleCredits(meta: BundleMeta | undefined): Credit[] {
		const out: Credit[] = [];
		for (const tier of meta?.tiers ?? []) {
			const c = tierCredit(meta, tier);
			if (!c) continue;
			const same = out.find((p) => p.name === c.name && p.url === c.url && p.catalog === c.catalog);
			if (same) same.tiers += `+${tier}`;
			else out.push(c);
		}
		return out;
	}

	// --- one shared renderer -------------------------------------------------

	let renderer: WebGLRenderer | undefined;
	let scene: Scene | undefined;
	let camera: PerspectiveCamera | undefined;
	/** Thumbnail jobs; a maximized viewer holds the renderer, so the queue parks
	 *  until it closes. A few run at once because the GLB download dominates —
	 *  each job's draw is synchronous after its await, so they never interleave
	 *  inside the shared scene. */
	const THUMB_CONCURRENCY = 3;
	let queue: (() => Promise<void>)[] = [];
	let running = 0;
	let disposed = false;

	function pump() {
		while (!disposed && !selected && running < THUMB_CONCURRENCY && queue.length > 0) {
			running += 1;
			queue.shift()!()
				.catch(() => {})
				.finally(() => {
					running -= 1;
					pump();
				});
		}
	}

	/** Load a bundle's GLB, normalised to unit radius at the origin under the
	 *  bundle's own frame map — the pose the main scene mounts it in. */
	async function loadModel(slug: string, tier: string): Promise<Object3D> {
		const meta = await ensureMeta(slug);
		const gltf = await modelLoader.loadAsync(
			versionedUrl(`/v1/models/${slug}/${tier}.glb`, 'models')
		);
		const frameQuat = meta.frame_map ? frameMapQuaternion(meta.frame_map) : null;
		if (frameQuat) gltf.scene.quaternion.copy(frameQuat);
		const root = new Group();
		root.add(gltf.scene);
		// Precise, so a card frames the mesh the way the scene sizes it.
		const sphere = new Box3().setFromObject(root, true).getBoundingSphere(new Sphere());
		if (sphere.radius > 0) {
			root.position.sub(sphere.center);
			const fitted = new Group();
			fitted.add(root);
			fitted.scale.setScalar(1 / sphere.radius);
			return fitted;
		}
		return root;
	}

	/** Three-quarter view from above, far enough out that a unit sphere fits. */
	function frame(aspect: number, azimuth: number) {
		if (!camera) return;
		const d = 1.35 / Math.sin(((camera.fov / 2) * Math.PI) / 180) / Math.min(1, aspect);
		camera.aspect = aspect;
		camera.position.set(Math.sin(azimuth) * d, 0.45 * d, Math.cos(azimuth) * d);
		camera.lookAt(0, 0, 0);
		camera.updateProjectionMatrix();
	}

	function thumbTier(b: Bundle): string {
		return b.tiers?.includes('low') ? 'low' : 'high';
	}

	async function drawThumb(b: Bundle, target: HTMLCanvasElement) {
		if (!renderer || !scene || !camera) return;
		const model = await loadModel(b.slug, thumbTier(b));
		try {
			scene.add(model);
			renderer.setSize(THUMB, THUMB, false);
			frame(1, 0.9);
			renderer.render(scene, camera);
			target.getContext('2d')?.drawImage(renderer.domElement, 0, 0, THUMB, THUMB);
			target.dataset.drawn = 'yes';
		} finally {
			scene.remove(model);
			disposeGltf(model);
		}
	}

	/** Card thumbnails render when they first scroll into view; a card that
	 *  leaves before its turn drops out of the queue. */
	function thumb(node: HTMLCanvasElement, b: Bundle) {
		let job: (() => Promise<void>) | null = null;
		const io = new IntersectionObserver((entries) => {
			if (!entries.some((e) => e.isIntersecting) || job || node.dataset.drawn) return;
			// Ahead of the draw queue: the credit shouldn't wait on a GLB.
			void ensureMeta(b.slug);
			job = () => drawThumb(b, node);
			queue.push(job);
			pump();
			io.disconnect();
		});
		io.observe(node);
		return {
			destroy() {
				io.disconnect();
				if (job) queue = queue.filter((j) => j !== job);
			}
		};
	}

	// --- maximized viewer ----------------------------------------------------

	let viewerHost = $state<HTMLDivElement | undefined>();
	let viewerModel: Object3D | undefined;
	let controls: OrbitControls | undefined;
	let animId: number | undefined;
	let viewerTier = $state('high');
	let viewerError = $state<string | null>(null);
	const viewerMeta = $derived(selected ? metas[selected.slug] : undefined);
	const viewerCredit = $derived(tierCredit(viewerMeta, viewerTier));

	function open(b: Bundle) {
		selected = b;
		viewerTier = b.tiers?.includes('high') ? 'high' : (b.tiers?.[0] ?? 'high');
	}

	function close() {
		selected = null;
	}

	function teardownViewer() {
		if (animId !== undefined) cancelAnimationFrame(animId);
		animId = undefined;
		controls?.dispose();
		controls = undefined;
		if (viewerModel && scene) {
			scene.remove(viewerModel);
			disposeGltf(viewerModel);
		}
		viewerModel = undefined;
		renderer?.domElement.remove();
	}

	$effect(() => {
		const b = selected;
		const host = viewerHost;
		const tier = viewerTier;
		if (!b || !host || !renderer || !scene || !camera) return;
		viewerError = null;
		let cancelled = false;
		host.append(renderer.domElement);
		const size = () => {
			const r = host.getBoundingClientRect();
			renderer!.setSize(Math.max(1, r.width), Math.max(1, r.height));
			frame(r.width / Math.max(1, r.height), 0.9);
			controls?.update();
		};
		controls = new OrbitControls(camera, renderer.domElement);
		controls.enableDamping = true;
		size();
		const ro = new ResizeObserver(size);
		ro.observe(host);

		loadModel(b.slug, tier)
			.then((model) => {
				if (cancelled) {
					disposeGltf(model);
					return;
				}
				viewerModel = model;
				scene!.add(model);
			})
			.catch((e) => {
				if (!cancelled) viewerError = String(e);
			});

		// Scheduled, never called inline: reading `spin` inside the effect body
		// would make the toggle a dependency and reload the mesh on every flip.
		const loop = () => {
			animId = requestAnimationFrame(loop);
			if (spin && viewerModel) viewerModel.rotation.y += 0.004;
			controls?.update();
			renderer!.render(scene!, camera!);
		};
		animId = requestAnimationFrame(loop);

		return () => {
			cancelled = true;
			ro.disconnect();
			teardownViewer();
			// The cards behind the overlay may still be waiting on the renderer.
			queueMicrotask(pump);
		};
	});

	// --- boot ----------------------------------------------------------------

	onMount(() => {
		renderer = new WebGLRenderer({ alpha: true, antialias: true });
		renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
		renderer.outputColorSpace = SRGBColorSpace;
		renderer.toneMapping = ACESFilmicToneMapping;
		scene = new Scene();
		scene.environment = makeEnvMap(renderer);
		scene.environmentIntensity = CRAFT_ENV_INTENSITY;
		camera = new PerspectiveCamera(35, 1, 0.01, 100);
		const key = new DirectionalLight(0xffffff, 3.1);
		key.position.set(-0.4, 0.45, 1);
		scene.add(key, new AmbientLight(0xffffff, 0.12));

		fetchMetadata()
			.then(() => fetch(versionedUrl('/v1/models/index.json', 'models')))
			.then((r) => {
				if (!r.ok) throw new Error(`index.json: ${r.status}`);
				return r.json();
			})
			.then((data: { bundles: Record<string, IndexBundle> }) => {
				bundles = Object.entries(data.bundles ?? {})
					.map(([slug, b]) => ({
						...b,
						slug,
						objects: b.objects ?? [],
						suspect: isSuspect(slug, b.objects ?? [])
					}))
					.sort((a, z) => a.slug.localeCompare(z.slug));
			})
			.catch((e) => (error = String(e)));

		return () => {
			disposed = true;
			queue = [];
			teardownViewer();
			scene?.environment?.dispose();
			renderer?.dispose();
			renderer = undefined;
		};
	});
</script>

<svelte:window
	onkeydown={(e) => {
		if (e.key === 'Escape' && selected) close();
	}}
/>

<main>
	<div class="page">
		<div class="controls">
			<input placeholder="slug or object name" bind:value={query} />
			<select bind:value={kindFilter}>
				<option value="craft">Spacecraft</option>
				<option value="shape">Shape models</option>
				<option value="all">All</option>
			</select>
			<label><input type="checkbox" bind:checked={onlyUnattached} /> attached to nothing</label>
			<label><input type="checkbox" bind:checked={onlySuspect} /> name mismatch</label>
			<span class="count">{shown.length} / {bundles.length}</span>
		</div>

		{#if error}
			<p class="error">
				{error} — run <code>ingest --targets models</code> to publish the index.
			</p>
		{/if}

		<ul class="grid">
			{#each shown as b (b.slug)}
				{@const meta = metas[b.slug]}
				{@const credits = bundleCredits(meta)}
				<li>
					<button onclick={() => open(b)} aria-label={`Maximize ${b.slug}`}>
						<canvas width={THUMB} height={THUMB} use:thumb={b}></canvas>
					</button>
					<h2>{b.slug}</h2>
					<p class="facts">
						{b.kind ?? '—'}
						{#if b.scale_meters}· {b.scale_meters} m{/if}
						{#if b.scale_meters && b.body_span_ratio && b.body_span_ratio < 0.9}
							· body {(b.scale_meters * b.body_span_ratio).toFixed(1)} m
						{/if}
						· {(b.tiers ?? []).join('+') || 'no tiers'}
					</p>
					{#if credits.length > 0}
						<ul class="credits">
							{#each credits as c (c.tiers)}
								<li>
									<span class="tiers">{c.tiers}</span>
									<a href={c.url} target="_blank" rel="noreferrer">{c.name}</a>
									{#if c.catalog}<span class="catalog">{c.catalog}</span>{/if}
									{#if c.license}<span class="license">{c.license}</span>{/if}
								</li>
							{/each}
						</ul>
					{:else if meta}
						<p class="warn">no credit in metadata.json</p>
					{/if}
					{#if b.objects.length === 0}
						<p class="none">attached to nothing</p>
					{:else}
						{#if b.suspect}
							<p class="warn">no object name matches the slug</p>
						{/if}
						<ul class="objects">
							{#each b.objects as o (o.id)}
								<li>
									<a href={bodyHref(o.id, o.name ?? '')}>{o.name ?? o.id}</a>
									<span class="id">{o.id}</span>
								</li>
							{/each}
						</ul>
					{/if}
				</li>
			{/each}
		</ul>
	</div>
</main>

{#if selected}
	<div class="overlay">
		<header>
			<h2>{selected.slug}</h2>
			<span class="facts">
				{selected.kind ?? '—'}
				{#if selected.scale_meters}· {selected.scale_meters} m{/if}
				{#if selected.scale_meters && selected.body_span_ratio}
					· body {(selected.scale_meters * selected.body_span_ratio).toFixed(2)} m
				{/if}
			</span>
			<label>
				tier
				<select bind:value={viewerTier}>
					{#each selected.tiers ?? ['high'] as t (t)}
						<option value={t}>{t}</option>
					{/each}
				</select>
			</label>
			<label><input type="checkbox" bind:checked={spin} /> spin</label>
			<button onclick={close}>Close (Esc)</button>
		</header>
		<div class="stage" bind:this={viewerHost}></div>
		<footer>
			{#if viewerError}
				<span class="error">{viewerError}</span>
			{:else if selected.objects.length === 0}
				<span class="none">attached to nothing</span>
			{:else}
				{#each selected.objects as o (o.id)}
					<a href={bodyHref(o.id, o.name ?? '')}>{o.name ?? o.id}</a>
				{/each}
			{/if}
			<span class="credit">
				{#if viewerCredit}
					{viewerTier} mesh ·
					<a href={viewerCredit.url} target="_blank" rel="noreferrer">{viewerCredit.name}</a>
					{#if viewerCredit.license}· {viewerCredit.license}{/if}
					{#if viewerCredit.catalog}· {viewerCredit.catalog}{/if}
					{#if viewerMeta?.provenance}· {viewerMeta.provenance}{/if}
					{#if viewerMeta?.archive}· {viewerMeta.archive}{/if}
				{:else if viewerMeta}
					<span class="warn">no credit in metadata.json</span>
				{/if}
			</span>
		</footer>
	</div>
{/if}

<style>
	main {
		/* html/body lock overflow for the 3D app, so own the scroll here. */
		position: fixed;
		inset: 0;
		overflow-y: auto;
		font-family: system-ui, sans-serif;
	}
	.page {
		max-width: 90rem;
		margin: 0 auto;
		padding: 2rem 1rem;
	}
	.controls {
		display: flex;
		flex-wrap: wrap;
		gap: 0.75rem;
		align-items: center;
		margin: 1rem 0;
		font-size: 0.85rem;
	}
	.controls input:not([type]) {
		padding: 0.35rem 0.5rem;
		min-width: 16rem;
	}
	.count {
		color: #888;
	}
	.grid {
		list-style: none;
		padding: 0;
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(14rem, 1fr));
		gap: 1.25rem;
	}
	.grid > li {
		border: 1px solid #2a2a2a;
		border-radius: 0.5rem;
		padding: 0.5rem;
	}

	.grid button {
		display: block;
		width: 100%;
		padding: 0;
		border: 0;
		background: #0b0b0f;
		border-radius: 0.375rem;
		cursor: zoom-in;
	}
	canvas {
		display: block;
		width: 100%;
		height: auto;
		aspect-ratio: 1;
	}
	.grid h2 {
		font-size: 0.9rem;
		margin: 0.5rem 0 0.15rem;
		word-break: break-all;
	}
	.facts {
		color: #888;
		font-size: 0.75rem;
		margin: 0;
	}
	.none,
	.warn {
		color: #b45309;
		font-size: 0.75rem;
		margin: 0.35rem 0 0;
	}
	.credits {
		list-style: none;
		padding: 0;
		margin: 0.35rem 0 0;
		font-size: 0.72rem;
		color: #888;
		display: flex;
		flex-direction: column;
		gap: 0.1rem;
	}
	.credits .tiers {
		color: #666;
	}
	.credits .tiers::after {
		content: ' ·';
	}
	.credits .catalog::before,
	.credits .license::before {
		content: '· ';
	}
	.credit {
		margin-left: auto;
		color: #888;
		font-size: 0.78rem;
	}
	.objects {
		list-style: none;
		padding: 0;
		margin: 0.4rem 0 0;
		font-size: 0.8rem;
		display: flex;
		flex-direction: column;
		gap: 0.15rem;
	}
	.objects .id {
		color: #666;
		font-size: 0.7rem;
		margin-left: 0.35rem;
	}
	.error {
		color: #dc2626;
	}
	.overlay {
		position: fixed;
		inset: 0;
		z-index: 50;
		background: #08080c;
		display: grid;
		grid-template-rows: auto 1fr auto;
	}
	.overlay header,
	.overlay footer {
		display: flex;
		flex-wrap: wrap;
		gap: 1rem;
		align-items: center;
		padding: 0.75rem 1rem;
		font-family: system-ui, sans-serif;
		font-size: 0.85rem;
	}
	.overlay header h2 {
		font-size: 1rem;
		margin: 0;
		margin-right: auto;
	}
	.stage {
		position: relative;
		min-height: 0;
		overflow: hidden;
	}
</style>
