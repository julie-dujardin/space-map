// Redraws the screenshots in docs/images from the built SDK, so that they follow
// the renderer and all come out of one crop.
//
//   pnpm screenshots [name…] [--data <export root>]
//
// Chromium is `$CHROME` when set, else the first one on the PATH, else the flatpak.
import { spawn, spawnSync } from 'node:child_process';
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { createServer } from 'node:http';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { setTimeout as sleep } from 'node:timers/promises';

const SDK = fileURLToPath(new URL('../dist/sdk/spacemap.js', import.meta.url));
const FONT = fileURLToPath(
	new URL(
		'../node_modules/@fontsource-variable/geist/files/geist-latin-wght-normal.woff2',
		import.meta.url
	)
);
const OUT = fileURLToPath(new URL('../../docs/images/', import.meta.url));

// Two shapes only: images that share a table row must share a size.
const TILE = { width: 1200, height: 800 };
const WIDE = { width: 1800, height: 900 };
// The page a shot is cropped out of. The field of view is vertical, so its
// height sets how large a body is drawn: this one is the window most of the
// links were framed in, and a shot framed in another gives its own `window`.
const PAGE_WIDTH = 2400;
const WINDOW = 1220;

// A view is a link to the site: to reframe a shot, paste the address of the
// view wanted, and give docs/images/README.md the same link. The crop is the
// middle of the page, moved by `shift` pixels to put the focused body off
// centre. `hide` lists layers left out of the picture.
const SHOTS = [
	{
		// The home page, from further back and higher up.
		name: 'inner-system',
		...WIDE,
		url: 'https://spacemap.co/',
		home: { elevationDeg: 45, zoom: 22 },
		shift: [0, -150]
	},
	{
		name: 'outer-system',
		...WIDE,
		url: 'https://spacemap.co/b/10?at=now,46.20563,-166.76342,927.46'
	},
	{
		name: 'artemis-2',
		...TILE,
		url: 'https://spacemap.co/p/121737217/Artemis%20II?at=2026-04-06T22:22:33.709Z,1.5,-14.75,2.9412e-8',
		window: 1740,
		shift: [-100, -90]
	},
	{
		name: 'mars',
		...TILE,
		url: 'https://spacemap.co/b/499/Mars?at=2026-06-03T05:09:05.427Z,-9.72405,91.33456,0.00093713'
	},
	{
		name: 'juno',
		...TILE,
		url: 'https://spacemap.co/p/107159552/Juno?at=2026-06-03T05:10:21.609Z,3.80217,41.36422,3.3423e-9',
		shift: [-200, 0]
	},
	{
		name: 'saturn',
		...TILE,
		url: 'https://spacemap.co/b/699/Saturn?at=2020-06-02T14:10:11.542Z,39.08590,-147.48087,0.06'
	},
	{
		name: 'iss',
		...TILE,
		url: 'https://spacemap.co/e/25544/International%20Space%20Station?at=2026-07-08T22:38:33.108Z,10.5,36,8.69e-9',
		shift: [140, -20],
		hide: ['labels']
	},
	{
		name: 'hubble',
		...TILE,
		url: 'https://spacemap.co/e/20580/Hubble%20Space%20Telescope?at=2026-07-26T11:43:18.534Z,7.05186,38.41685,1.4104e-9',
		hide: ['labels', 'orbits', 'satellites', 'debris']
	},
	{
		name: 'earth',
		...TILE,
		url: 'https://spacemap.co/b/399/Earth?at=2026-06-21T14:24:57.661Z,30.63812,-22.71399,0.0023'
	},
	{
		name: 'curiosity',
		...TILE,
		url: 'https://spacemap.co/p/100265984/Mars%20Science%20Laboratory?at=2026-07-28T14:17:41.132Z,-52,-72.77,6.016e-10',
		shift: [0, -120]
	}
];

const ID_PREFIX = { b: 'naif', s: 'spkid', e: 'norad_satcat', p: 'probe', u: 'extra' };
// The zoom of an `?at=` block is a distance in scene units, ten to the AU.
const SCENE_UNIT_KM = 149_597_870.7 / 10;

/** The `createMap` options that open the map where a shot's link does. A
 *  link with no `at` block is the home page: Earth, with the Sun behind it. */
function mapOptions({ url, home, hide }) {
	const { pathname, searchParams } = new URL(url);
	const at = searchParams.get('at');
	if (!at) {
		const { elevationDeg, zoom } = home;
		const view = { body: 'naif-399', facing: 'naif-10', elevationDeg };
		return { hide, view: { ...view, distanceKm: zoom * SCENE_UNIT_KM } };
	}
	const [, type, id] = pathname.split('/');
	const [date, lat, lon, zoom] = at.split(',');
	return {
		hide,
		date: date === 'now' ? undefined : date,
		view: {
			body: `${ID_PREFIX[type]}-${id}`,
			lat: +lat,
			lon: +lon,
			distanceKm: zoom * SCENE_UNIT_KM
		}
	};
}

const PAGE = `<!doctype html>
<meta charset="utf-8" />
<style>
	/* The SDK takes the font of its page; this is the site's. */
	@font-face {
		font-family: 'Geist Variable';
		font-weight: 100 900;
		src: url('./geist.woff2') format('woff2-variations');
	}
	html, body { margin: 0; background: #000; font-family: 'Geist Variable', sans-serif; }
	#map { width: 100vw; height: 100vh; }
</style>
<div id="map"></div>
<script type="module">
	import { createMap } from './spacemap.js';
	const { date, view, hide, dataUrl } = JSON.parse(new URLSearchParams(location.search).get('options'));
	window.loading = true;
	try {
		await document.fonts.load('16px "Geist Variable"');
		const map = await createMap({
			container: '#map',
			interactive: false,
			view,
			date: date && new Date(date),
			...(dataUrl && { dataUrl }),
			events: { loading: (loading) => (window.loading = loading) }
		});
		for (const layer of hide ?? []) map.setLayerVisible(layer, false);
		// The layer takes the names away and leaves the halos they sit beside.
		if (hide?.includes('labels')) document.querySelector('.scene-overlay').hidden = true;
		// What arrives under a stopped clock is placed by the next change of
		// date; without one the small bodies are missing.
		window.place = () => map.clock.setDate(map.clock.date);
		// The map opens on its own framing of the body: it takes no view facing
		// another body, and a satellite, a rover or a small body is known too
		// late for one. The view is put back until it holds. The clock runs
		// until then, as a rover is not placed under a stopped one, and goes
		// back to the date of the view: a still scene is what lets two captures
		// in a row be compared.
		let aimed = false;
		let still = false;
		window.aim = () => {
			const camera = map.getCamera();
			const there =
				aimed &&
				camera?.body === view.body &&
				Math.abs(camera.distanceKm / view.distanceKm - 1) < 0.01;
			if (!there && map.getBody(view.body)) {
				map.jumpTo(view);
				aimed = true;
			}
			if (there && !still) {
				still = true;
				map.clock.pause();
				if (date) map.clock.setDate(new Date(date));
			}
			return still;
		};
	} catch (error) {
		window.failure = String(error);
	}
</script>`;

function serve() {
	const server = createServer((request, response) => {
		const [type, body] = request.url.startsWith('/spacemap.js')
			? ['text/javascript', readFileSync(SDK)]
			: request.url.startsWith('/geist.woff2')
				? ['font/woff2', readFileSync(FONT)]
				: ['text/html', PAGE];
		response.setHeader('content-type', type);
		response.end(body);
	});
	return new Promise((resolve) => server.listen(0, '127.0.0.1', () => resolve(server)));
}

function chromiumCommand(profile) {
	if (process.env.CHROME) return process.env.CHROME.split(' ');
	for (const name of ['chromium', 'chromium-browser', 'google-chrome', 'google-chrome-stable'])
		if (spawnSync('which', [name]).status === 0) return [name];
	// The sandbox hides the host's temporary directory, where the profile is.
	return ['flatpak', 'run', `--filesystem=${profile}`, 'org.chromium.Chromium'];
}

/** Start a headless Chromium and talk to it over one DevTools socket. */
async function launch(profile) {
	const [command, ...args] = chromiumCommand(profile);
	const child = spawn(
		command,
		[...args, '--headless=new', '--remote-debugging-port=0', `--user-data-dir=${profile}`],
		{ stdio: 'ignore' }
	);
	const exited = new Promise((_, reject) => {
		child.on('error', reject);
		child.on('exit', (code) => reject(new Error(`Chromium exited with ${code}`)));
	});
	// Chromium writes the port it picked, then the socket path, to this file.
	const portFile = join(profile, 'DevToolsActivePort');
	const started = (async () => {
		while (!existsSync(portFile) || !readFileSync(portFile, 'utf8').includes('\n'))
			await sleep(100);
	})();
	await Promise.race([started, exited]);
	const [port, path] = readFileSync(portFile, 'utf8').split('\n');

	const socket = new WebSocket(`ws://127.0.0.1:${port}${path}`);
	await new Promise((resolve, reject) => {
		socket.onopen = resolve;
		socket.onerror = () => reject(new Error('could not reach Chromium'));
	});
	const pending = new Map();
	const listeners = new Set();
	socket.onmessage = ({ data }) => {
		const message = JSON.parse(data);
		if (!message.id) return listeners.forEach((listener) => listener(message));
		const { resolve, reject } = pending.get(message.id);
		pending.delete(message.id);
		if (message.error) reject(new Error(message.error.message));
		else resolve(message.result);
	};
	let lastId = 0;
	const send = (method, params = {}, sessionId) =>
		new Promise((resolve, reject) => {
			pending.set(++lastId, { resolve, reject });
			socket.send(JSON.stringify({ id: lastId, method, params, sessionId }));
		});
	return { send, listeners };
}

async function capture(browser, sessionId, origin, shot) {
	const send = (method, params) => browser.send(method, params, sessionId);
	const page = shot.window ?? WINDOW;
	const [dx, dy] = shot.shift ?? [0, 0];
	const evaluate = async (expression) =>
		(await send('Runtime.evaluate', { expression, returnByValue: true })).result.value;
	await send('Emulation.setDeviceMetricsOverride', {
		width: PAGE_WIDTH,
		height: page,
		deviceScaleFactor: 1,
		mobile: false
	});
	const options = encodeURIComponent(JSON.stringify(shot.options));
	await send('Page.navigate', { url: `${origin}/?options=${options}` });

	const clip = {
		x: (PAGE_WIDTH - shot.width) / 2 + dx,
		y: (page - shot.height) / 2 + dy,
		width: shot.width,
		height: shot.height,
		scale: 1
	};
	// Textures, models and small bodies arrive after the map opens, and nothing
	// says when the last of them is drawn: wait for the picture to stop changing.
	const still = async () => {
		const deadline = Date.now() + 60_000;
		let previous = null;
		let repeats = 0;
		for (;;) {
			await sleep(2000);
			const failure = await evaluate('window.failure');
			if (failure) throw new Error(`${shot.name}: ${failure}`);
			const settled = await evaluate('window.aim?.() && !window.loading');
			const { data } = await send('Page.captureScreenshot', { format: 'png', clip });
			repeats = settled && data === previous ? repeats + 1 : 0;
			if (repeats === 2) return data;
			if (Date.now() > deadline) {
				console.warn(`${shot.name}: still changing after a minute, kept the last frame`);
				return data;
			}
			previous = data;
		}
	};
	await still();
	await evaluate('window.place()');
	return Buffer.from(await still(), 'base64');
}

const args = process.argv.slice(2);
const dataFlag = args.indexOf('--data');
const dataUrl = dataFlag < 0 ? null : args.splice(dataFlag, 2)[1];
const unknown = args.filter((name) => !SHOTS.some((shot) => shot.name === name));
if (unknown.length) throw new Error(`no such screenshot: ${unknown.join(', ')}`);
if (!existsSync(SDK)) throw new Error('dist/sdk is missing — run pnpm build:sdk');

const server = await serve();
const origin = `http://127.0.0.1:${server.address().port}`;
const profile = mkdtempSync(join(tmpdir(), 'spacemap-screenshots-'));
const browser = await launch(profile);
try {
	browser.listeners.add(({ method, params }) => {
		if (method === 'Runtime.exceptionThrown')
			console.warn(params.exceptionDetails.exception?.description ?? params.exceptionDetails.text);
	});

	for (const shot of SHOTS) {
		if (args.length && !args.includes(shot.name)) continue;
		const options = mapOptions(shot);
		if (dataUrl) options.dataUrl = dataUrl;
		const started = Date.now();
		// A context of its own: on data left in the cache by an earlier shot,
		// the map never places a rover.
		const { browserContextId } = await browser.send('Target.createBrowserContext');
		const { targetId } = await browser.send('Target.createTarget', {
			url: 'about:blank',
			browserContextId
		});
		const { sessionId } = await browser.send('Target.attachToTarget', { targetId, flatten: true });
		await browser.send('Runtime.enable', {}, sessionId);
		const png = await capture(browser, sessionId, origin, { ...shot, options });
		await browser.send('Target.disposeBrowserContext', { browserContextId });
		writeFileSync(join(OUT, `${shot.name}.png`), png);
		const seconds = ((Date.now() - started) / 1000).toFixed(0);
		console.log(`${shot.name}.png ${shot.width}×${shot.height} in ${seconds} s`);
	}
} finally {
	await browser.send('Browser.close').catch(() => {});
	server.close();
	rmSync(profile, { recursive: true, force: true });
}
