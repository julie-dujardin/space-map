/**
 * Scene scenarios: drives the real app in a headless browser and checks what
 * the scene holds. They cover the two rules no unit test can see end to end:
 *
 * - a body with no known place is not drawn, and the camera is never on a
 *   stand-in for it;
 * - a navigation to an object moves the clock to a date the object has a place at.
 *
 * Needs a dev server (its build exposes `__smCtx`, `__smRenderer`, `__smMap`)
 * on an export that carries `coverage`, and a Chromium with remote debugging:
 *
 *   chromium --headless=new --remote-debugging-port=9222 about:blank
 *   pnpm dev
 *   SM_URL=http://localhost:5173 SM_CDP=http://127.0.0.1:9222 pnpm test:scenes [name...]
 */

const URL_BASE = process.env.SM_URL ?? 'http://localhost:5173';
const CDP = process.env.SM_CDP ?? 'http://127.0.0.1:9222';
const TIMEOUT_MS = 60_000;
const J2000 = 2451545;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** One browser tab, driven over the DevTools protocol. */
class Tab {
	static async open() {
		const target = await (await fetch(`${CDP}/json/new?about:blank`, { method: 'PUT' })).json();
		const tab = new Tab(target);
		await new Promise((resolve, reject) => {
			tab.ws.addEventListener('open', resolve, { once: true });
			tab.ws.addEventListener('error', reject, { once: true });
		});
		await tab.send('Page.enable');
		await tab.send('Runtime.enable');
		await tab.send('Emulation.setDeviceMetricsOverride', {
			width: 1600,
			height: 900,
			deviceScaleFactor: 1,
			mobile: false
		});
		return tab;
	}

	constructor(target) {
		this.target = target;
		this.ws = new WebSocket(target.webSocketDebuggerUrl);
		this.seq = 0;
		this.pending = new Map();
		this.exceptions = [];
		this.ws.addEventListener('message', (event) => {
			const msg = JSON.parse(event.data);
			if (msg.id && this.pending.has(msg.id)) {
				this.pending.get(msg.id)(msg.result ?? msg);
				this.pending.delete(msg.id);
			}
			if (msg.method === 'Runtime.exceptionThrown') {
				const d = msg.params.exceptionDetails;
				this.exceptions.push(d.exception?.description ?? d.text);
			}
		});
	}

	send(method, params = {}) {
		return new Promise((resolve) => {
			this.pending.set(++this.seq, resolve);
			this.ws.send(JSON.stringify({ id: this.seq, method, params }));
		});
	}

	async eval(expression) {
		const r = await this.send('Runtime.evaluate', {
			expression,
			returnByValue: true,
			awaitPromise: true
		});
		if (r.exceptionDetails)
			throw new Error(r.exceptionDetails.exception?.description ?? 'eval failed');
		return r.result?.value;
	}

	async goto(path) {
		this.exceptions.length = 0;
		await this.send('Page.navigate', { url: URL_BASE + path });
	}

	/** Poll `expression` until it is truthy. */
	async until(expression, what) {
		const deadline = Date.now() + TIMEOUT_MS;
		while (Date.now() < deadline) {
			if (await this.eval(expression).catch(() => false)) return;
			await sleep(250);
		}
		throw new Error(`timed out waiting for ${what}`);
	}

	async close() {
		await fetch(`${CDP}/json/close/${this.target.id}`);
		this.ws.close();
	}
}

/** Runs in the page: what the scene holds for `id`, and what must hold for every body. */
const SNAPSHOT = `((id) => {
	const ctx = window.__smCtx, r = window.__smRenderer;
	const body = ctx.getBody(id);
	const bo = r.bodyObjects.get(id);
	const km = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]) * 14959787.07;
	const basis = r.focus.focusTruePos;
	const earth = ctx.getBody('naif-399')?.position, emb = ctx.getBody('naif-3')?.position;
	const leaks = [];
	for (const o of r.bodyObjects.values()) {
		if (o.body.position) continue;
		if (o.root.visible) leaks.push(o.body.data.id + ':root');
		if (o.trail?.visible) leaks.push(o.body.data.id + ':trail');
		if (o.model?.parent === r.modelScene) leaks.push(o.body.data.id + ':model');
	}
	return {
		jd: r.clock.jd,
		inScene: !!body,
		placed: !!body?.position,
		unplaced: body?.unplaced ?? null,
		focused: r.focusController.current?.data.id ?? null,
		cameraToBodyKm: body?.position ? km(basis, body.position) : null,
		cameraToEarthKm: earth ? km(basis, earth) : null,
		bodyToEarthKm: body?.position && earth ? km(body.position, earth) : null,
		earthOffBarycentreKm: earth && emb ? km(earth, emb) : null,
		basisAtOrigin: Math.hypot(...basis) < 1e-9,
		drawn: !!bo?.root.visible,
		leaks,
		toasts: [...document.querySelectorAll('[data-sonner-toast]')].map((e) => e.innerText)
	};
})`;

const READY = `!!window.__smRenderer && !!window.__smMap && window.__smCtx?.loading === false`;
const focusedIs = (id) => `window.__smRenderer?.focusController.current?.data.id === '${id}'`;
const goTo = (id) =>
	`window.__smMap.goTo('${id}').then((a) => ({ outcome: a.outcome, moved: !!a.clockMoved, host: a.host?.data.id ?? null }))`;
const jdOf = (iso) => Date.parse(iso) / 86400000 + 2440587.5;

function check(failures, ok, message) {
	if (!ok) failures.push(message);
}

/** What must hold after every scenario. */
function invariants(failures, s) {
	check(failures, s.leaks.length === 0, `drawn with no place: ${s.leaks.join(', ')}`);
	check(failures, !s.basisAtOrigin, 'the camera basis is on the barycentre of the Solar System');
	check(
		failures,
		s.earthOffBarycentreKm === null || s.earthOffBarycentreKm > 1000,
		`Earth is ${s.earthOffBarycentreKm} km from the Earth-Moon barycentre`
	);
}

const MIR = 'norad_satcat-16609';
const ISS = 'norad_satcat-25544';
const SPUTNIK = 'norad_satcat-2';

const SCENARIOS = {
	/** A satellite that re-entered in 2001, opened today. */
	async 'decayed satellite opens at its last covered date'(tab, f) {
		await tab.goto('/e/16609/Mir');
		await tab.until(
			`${READY} && ${focusedIs(MIR)} && !!window.__smCtx.getBody('${MIR}')?.position`,
			'Mir placed'
		);
		const s = await tab.eval(`${SNAPSHOT}('${MIR}')`);
		check(
			f,
			s.jd > jdOf('2001-03-01') && s.jd < jdOf('2001-03-23'),
			`clock at jd ${s.jd}, not in March 2001`
		);
		check(f, s.cameraToBodyKm < 1, `camera ${s.cameraToBodyKm} km from Mir`);
		check(f, s.bodyToEarthKm < 7000, `Mir ${s.bodyToEarthKm} km from Earth`);
		check(
			f,
			s.toasts.some((t) => t.includes('2001')),
			'no notice that the date changed'
		);
		return s;
	},

	/** The archive starts in 1959: nothing can place Sputnik 1. */
	async 'object with no place opens its page and frames its host'(tab, f) {
		await tab.goto('/e/2/Sputnik%201');
		await tab.until(`${READY} && ${focusedIs(SPUTNIK)}`, 'Sputnik 1 focused');
		await sleep(3000);
		const s = await tab.eval(`${SNAPSHOT}('${SPUTNIK}')`);
		check(f, !s.placed && s.unplaced === 'never', `placed=${s.placed} unplaced=${s.unplaced}`);
		check(f, !s.drawn, 'its root is drawn');
		check(f, s.cameraToEarthKm < 1, `camera ${s.cameraToEarthKm} km from Earth`);
		check(f, Math.abs(s.jd - jdOf(new Date().toISOString())) < 1, 'the clock moved');
		check(
			f,
			s.toasts.some((t) => t.includes('Earth')),
			'no notice that the map shows Earth'
		);
		return s;
	},

	async 'satellite deep link inside its coverage keeps the date'(tab, f) {
		await tab.goto('/e/16609/Mir?at=1995-06-01T12:00:00.000Z');
		await tab.until(
			`${READY} && ${focusedIs(MIR)} && !!window.__smCtx.getBody('${MIR}')?.position`,
			'Mir placed'
		);
		const s = await tab.eval(`${SNAPSHOT}('${MIR}')`);
		check(f, Math.abs(s.jd - jdOf('1995-06-01T12:00:00Z')) < 0.01, `clock at jd ${s.jd}`);
		check(f, s.bodyToEarthKm < 7000, `Mir ${s.bodyToEarthKm} km from Earth`);
		check(f, s.toasts.length === 0, `toasts: ${s.toasts.join(' | ')}`);
		return s;
	},

	/** The current elements of the ISS do not reach 2010: the row of that week does. */
	async 'live satellite at an old date uses the elements of that date'(tab, f) {
		await tab.goto('/e/25544/ISS?at=2010-01-01T00:00:00.000Z');
		await tab.until(
			`${READY} && ${focusedIs(ISS)} && !!window.__smCtx.getBody('${ISS}')?.position`,
			'ISS placed'
		);
		const s = await tab.eval(`${SNAPSHOT}('${ISS}')`);
		check(f, Math.abs(s.jd - jdOf('2010-01-01T00:00:00Z')) < 0.01, `clock at jd ${s.jd}`);
		check(f, s.bodyToEarthKm < 7000, `ISS ${s.bodyToEarthKm} km from Earth`);
		return s;
	},

	async 'moon opened before its discovery goes to the discovery date'(tab, f) {
		await tab.goto('/b/904/Kerberos?at=2000-01-01T00:00:00.000Z');
		await tab.until(
			`${READY} && ${focusedIs('naif-904')} && !!window.__smCtx.getBody('naif-904')?.position`,
			'Kerberos placed'
		);
		const s = await tab.eval(`${SNAPSHOT}('naif-904')`);
		check(f, s.jd > J2000 + 4000, `clock at jd ${s.jd}, before the discovery`);
		check(f, s.cameraToBodyKm < 1, `camera ${s.cameraToBodyKm} km from Kerberos`);
		return s;
	},

	async 'in-session navigation moves the clock, then places and frames'(tab, f) {
		await tab.goto('/e/25544/ISS');
		await tab.until(`${READY} && ${focusedIs(ISS)}`, 'ISS focused');
		const toMir = await tab.eval(goTo(MIR));
		check(f, toMir.outcome === 'placed' && toMir.moved, `to Mir: ${JSON.stringify(toMir)}`);
		// Launched in 2019: the clock leaves 2001 for it.
		const toStarlink = await tab.eval(goTo('norad_satcat-44714'));
		check(
			f,
			toStarlink.outcome === 'placed' && toStarlink.moved,
			`to Starlink: ${JSON.stringify(toStarlink)}`
		);
		const toSputnik = await tab.eval(goTo(SPUTNIK));
		check(
			f,
			toSputnik.outcome === 'host' && toSputnik.host === 'naif-399',
			`to Sputnik 1: ${JSON.stringify(toSputnik)}`
		);
		const s = await tab.eval(`${SNAPSHOT}('norad_satcat-44714')`);
		check(f, s.jd > jdOf('2019-11-01'), `clock at jd ${s.jd}`);
		return s;
	},

	async 'later navigation supersedes an earlier one'(tab, f) {
		await tab.goto('/e/25544/ISS');
		await tab.until(`${READY} && ${focusedIs(ISS)}`, 'ISS focused');
		const [first, second] = await tab.eval(
			`Promise.all([${goTo('probe-49065984')}, ${goTo(MIR)}])`
		);
		check(f, first.outcome === 'superseded', `first: ${first.outcome}`);
		check(f, second.outcome === 'placed', `second: ${second.outcome}`);
		await sleep(2500);
		const s = await tab.eval(`${SNAPSHOT}('${MIR}')`);
		check(f, s.focused === MIR, `focused ${s.focused}`);
		return s;
	},

	async 'live satellite today has a place and no notice'(tab, f) {
		await tab.goto('/e/44714/STARLINK-1008');
		await tab.until(
			`${READY} && ${focusedIs('norad_satcat-44714')} && !!window.__smCtx.getBody('norad_satcat-44714')?.position`,
			'Starlink placed'
		);
		await sleep(1500);
		const s = await tab.eval(`${SNAPSHOT}('norad_satcat-44714')`);
		check(f, s.cameraToBodyKm < 1, `camera ${s.cameraToBodyKm} km from the satellite`);
		check(f, s.toasts.length === 0, `toasts: ${s.toasts.join(' | ')}`);
		return s;
	},

	/** Through the page's own navigation: a featured chip, then the Back button. */
	async 'back returns to the object and to its date'(tab, f) {
		await tab.goto('/e/16609/Mir');
		await tab.until(`${READY} && ${focusedIs(MIR)}`, 'Mir focused');
		await sleep(1500);
		const clicked = await tab.eval(
			`(() => { const chip = [...document.querySelectorAll('a, button')].find((e) => e.textContent.trim() === 'Mars'); chip?.click(); return !!chip; })()`
		);
		check(f, clicked, 'no Mars chip to click');
		await tab.until(focusedIs('naif-499'), 'Mars focused');
		await sleep(1500);
		await tab.eval('history.back()');
		await tab.until(
			`${focusedIs(MIR)} && !!window.__smCtx.getBody('${MIR}')?.position`,
			'Mir focused again'
		);
		await sleep(2500);
		const s = await tab.eval(`${SNAPSHOT}('${MIR}')`);
		check(f, s.jd > jdOf('2001-03-01') && s.jd < jdOf('2001-03-23'), `clock at jd ${s.jd}`);
		check(f, s.cameraToBodyKm < 1, `camera ${s.cameraToBodyKm} km from Mir`);
		return s;
	},

	async 'home view'(tab, f) {
		await tab.goto('/b/399/Earth');
		await tab.until(`${READY} && ${focusedIs('naif-399')}`, 'Earth focused');
		await sleep(1500);
		const s = await tab.eval(`${SNAPSHOT}('naif-399')`);
		check(
			f,
			s.placed && s.cameraToBodyKm < 1,
			`Earth placed=${s.placed}, camera ${s.cameraToBodyKm} km away`
		);
		check(f, s.toasts.length === 0, `toasts: ${s.toasts.join(' | ')}`);
		return s;
	}
};

const wanted = process.argv.slice(2);
const names = Object.keys(SCENARIOS).filter(
	(n) => wanted.length === 0 || wanted.some((w) => n.includes(w))
);
let failed = 0;
for (const name of names) {
	const tab = await Tab.open();
	const failures = [];
	try {
		const snapshot = await SCENARIOS[name](tab, failures);
		invariants(failures, snapshot);
		// The search service is not part of the scene: its absence is not a failure.
		const thrown = tab.exceptions.filter((e) => !/meilisearch/i.test(e));
		check(failures, thrown.length === 0, `uncaught: ${thrown.slice(0, 3).join(' | ')}`);
	} catch (e) {
		failures.push(String(e.message ?? e));
	} finally {
		await tab.close();
	}
	if (failures.length > 0) failed++;
	console.log(`${failures.length === 0 ? 'ok  ' : 'FAIL'} ${name}`);
	for (const f of failures) console.log(`       ${f}`);
}
console.log(`\n${names.length - failed}/${names.length} scenarios passed`);
process.exit(failed === 0 ? 0 : 1);
