import { MathUtils, Matrix4, Quaternion, Vector3, type PerspectiveCamera } from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { TwoFingerGesture, type Point } from './two-finger';

/** Steepest tilt off the vertical. Short of the horizon, so the ground still
 *  fills the lower part of the view and the camera stays above it. */
export const MAX_TILT = MathUtils.degToRad(80);

/** Height over the ground, in radii, under which the view tilts freely, and
 *  from which it does not at all: out in space a tilt only gets in the way of
 *  finding things. In between, the tilt allowed shrinks, and zooming back in
 *  does not give back what it lost. */
export const LOOK_FULL_HEIGHT = 0.5;
export const LOOK_NONE_HEIGHT = 1;

/** The view's turn, in radians: `tilt` off the vertical toward the horizon,
 *  `heading` round the vertical off north, counterclockwise as seen from above. */
export interface LookAngles {
	tilt: number;
	heading: number;
}

export const LEVEL_LOOK: Readonly<LookAngles> = { tilt: 0, heading: 0 };

/** Middle-drag and two-finger turn rate: half a turn per viewport height. */
const TURN_PER_HEIGHT = Math.PI;

/** Turn back toward north per radian the orbit travels, against the drift a
 *  sideways drag makes: tan(latitude) per radian, which this outpulls
 *  wherever it acts in full. */
const NORTH_PULL = 1.5;

/** Heading off north inside which a drag pulls the view back to it, and
 *  outside which it lets the view be: one turned well away, as over a pole,
 *  stays where it went. */
const NORTH_HOLD_FULL = MathUtils.degToRad(15);
const NORTH_HOLD_NONE = MathUtils.degToRad(30);

/** Angle of the view off the pole, as its sine, inside which the pull
 *  weakens, and inside which it stops: a drag near a pole goes round or over
 *  it freely. */
const NORTH_PULL_FULL = Math.sin(MathUtils.degToRad(25));
const NORTH_PULL_NONE = Math.sin(MathUtils.degToRad(10));

/** Share of what is left that a reset to north turns per frame, against the
 *  orbit's damping. */
const SEEK_PER_DAMPING = 2;

/** Heading error, in radians, under which a reset to north is done. */
const SEEK_DONE = 1e-4;

/** Turn, in radians, under which keeping the heading is not reported as a
 *  change: no pixel moves for it, as for three's own. */
const TURN_SEEN = 1e-3;

/** Sine of the view's angle off the north axis under which north says
 *  nothing about the heading: straight over a pole. */
const MIN_NORTH_CLARITY = 1e-3;

const _y = new Vector3(0, 1, 0);
const _n = new Vector3();
const _right = new Vector3();
const _up = new Vector3();
const _north = new Vector3();
const _pivot = new Vector3();
const _qRoll = new Quaternion();
const _qTilt = new Quaternion();
const _ray = new Vector3();
const _from = new Vector3();
const _to = new Vector3();
const _anchor = new Vector3();
const _hit = new Vector3();
const _turnBack = new Quaternion();
const _pivotGround = new Vector3();
const _look = new Matrix4();

/** Turn still to come, in radians, under which a glide is done. */
const GLIDE_DONE = 1e-5;

/** Passes that put the ground back under the pointer after a zoom. */
const ANCHOR_PASSES = 3;

/** Least elevation of the pointer's ray over the ground for the wheel to keep
 *  that ground put, as three's own cursor zoom stops near the horizon. */
const SIN_MIN_ANCHOR_ELEVATION = Math.sin(MathUtils.degToRad(20));

/** Passes that find where a ray lands on relief, each from the last one's height. */
const GROUND_PASSES = 3;

/** Change in the ground under the orbit, as a share of its radius, below
 *  which the swing point stays: a metre or so on a planet, not the rounding
 *  of each frame's read. */
const PIVOT_REFINE = 1e-7;

/** A touch as three's handlers read it. */
interface TouchPoint {
	pointerId: number;
	pageX: number;
	pageY: number;
}

/** The handlers three keeps off its typings. */
interface PointerHandlers {
	_handleTouchStartDollyPan(event: TouchPoint): void;
	_handleTouchMoveDollyPan(event: TouchPoint): void;
	_handleMouseWheel(event: WheelEvent): void;
}
const orbitHandlers = OrbitControls.prototype as unknown as PointerHandlers;

/** The touch state three keeps off its typings. */
interface TouchState {
	_pointers: number[];
	_pointerPositions: Record<number, Point>;
}

/** The up→Y frame three caches at construction and orbits in. */
interface OrbitFrame {
	_quat: Quaternion;
	_quatInverse: Quaternion;
}

/**
 * How the heading is kept: `soft` pulls a drag's drift back to north when
 * the view is near it; `exact` keeps a placed heading off north while north turns, until
 * the reader moves; `seek` turns the view to north.
 */
type HeadingHold = 'soft' | 'exact' | 'seek';

/**
 * OrbitControls that orbit about the view's own up rather than north, as a
 * globe does: there is no pole to stop at or spin round. `camera.up` is north,
 * which the heading is read off and a drag's drift is pulled back toward.
 *
 * A middle drag tilts and turns the view about the ground at its centre, the
 * way a map does: up and down tilt it toward the horizon, left and right turn
 * the heading. On a touch screen two fingers sliding up or down side by side
 * tilt it, and a twist turns the heading while they pinch and pan. With
 * damping on, a tilt or a turn glides on after the gesture. The wheel keeps
 * the ground under the pointer where it is.
 *
 * Whatever else places the camera (a focus change, a fly, a snap, a held
 * pose) ends the tilt where it stands, so a transition starts from the view
 * on screen. A limit that holds the camera holds the orbit with it.
 */
export class LookOrbitControls extends OrbitControls {
	declare object: PerspectiveCamera;
	private tilt = 0;
	/** Whether the camera stands tilted off the orbit pose below. */
	private looking = false;
	private readonly orbitPos = new Vector3();
	private readonly orbitQuat = new Quaternion();
	/** Height of the ground the view turns about, from the target. */
	private pivotRadius = 0;
	/** The view stands where a placement named it (a link, a jump) and the
	 *  reader has not moved since: as the ground under it refines, the camera
	 *  follows, so the view opens the same however fast the ground loads. */
	private placedByName = false;
	private hold: HeadingHold = 'soft';
	private heldHeading = 0;
	/** The heading last read, standing in where north says nothing. */
	private lastHeading = 0;
	/** How square north lies to the view, read with the heading. */
	private northClarity = 0;
	/** North stands at its reference: it is not turning to a new one. */
	northSettled = true;
	/** How far, in radians, the last orbit step carried the camera round. */
	private travel = 0;
	/** A tilt placed before there was ground to tilt over (a link opening
	 *  while its body loads): it applies once there is, unless the reader
	 *  moves first. */
	private pendingLook: LookAngles | null = null;
	/** The orbit moved since the frame's clamps last ran: a gesture or its
	 *  inertia, which can carry it into the ground. */
	private orbitMoved = false;
	/** The pose this placed last, to tell another writer's from its own. */
	private readonly placedPos = new Vector3();
	private readonly placedQuat = new Quaternion();
	private dragPointer: number | null = null;
	private dragX = 0;
	private dragY = 0;
	private readonly twoFinger = new TwoFingerGesture();
	/** Turn a gesture asked for that the damping has not given yet, in radians. */
	private glideHeading = 0;
	private glideTilt = 0;

	constructor(
		camera: PerspectiveCamera,
		private readonly canvas: HTMLElement,
		/** Distance from the target to its ground along a unit direction, in
		 *  scene units; null for none, and no tilt. */
		private readonly surfaceRadius: (direction: Vector3) => number | null,
		/** The turn settled where nobody's gesture put it: the view to report. */
		private readonly onTurnSettled: () => void = () => {}
	) {
		super(camera, canvas);
		this.mouseButtons.MIDDLE = null;
		this.addEventListener('start', () => {
			this.pendingLook = null;
			this.placedByName = false;
			this.hold = 'soft';
		});
		canvas.addEventListener('pointerdown', this.onLookDown);
		// Middle-button autoscroll and paste ride on mousedown.
		canvas.addEventListener('mousedown', this.blockMiddle);
		canvas.addEventListener('pointerdown', this.onCatch);
	}

	/** Where the orbit holds the camera, under any tilt. */
	get orbitPosition(): Vector3 {
		return this.looking ? this.orbitPos : this.object.position;
	}

	/** Whether the view stands tilted off the orbit pose. */
	get turned(): boolean {
		return this.looking;
	}

	/** The view's heading off north, in radians, as {@link LookAngles} has it. */
	get heading(): number {
		return this.pendingLook?.heading ?? this.readHeading() ?? this.lastHeading;
	}

	/** The view's turn as it stands, or as placed while it waits for ground. */
	get look(): LookAngles {
		if (this.pendingLook) return { ...this.pendingLook };
		return { tilt: this.looking ? this.tilt : 0, heading: this.heading };
	}

	/** Turn the view off the orbit pose the camera is on: the heading at once,
	 *  the tilt as far as its height allows. A placement that names a view. */
	setLook({ tilt, heading }: LookAngles): void {
		const cam = this.object;
		this.looking = false;
		this.pendingLook = null;
		this.placedByName = false;
		this.stopGlide();
		this.faceHeading(heading);
		this.heldHeading = heading;
		this.hold = 'exact';
		if (tilt === 0) return;
		if (!this.groundKnown()) {
			this.pendingLook = { tilt, heading };
			return;
		}
		const share = this.lookShare();
		if (share === 0) return;
		this.orbitPos.copy(cam.position);
		this.orbitQuat.copy(cam.quaternion);
		this.samplePivot();
		this.tilt = MathUtils.clamp(tilt, 0, MAX_TILT);
		this.holdAngles(share);
		this.looking = true;
		this.placedByName = true;
		this.place();
	}

	/** Turn the view round the centre of the screen until north is up. The
	 *  tilt stays. */
	resetNorth(): void {
		this.stopGlide();
		if (this.pendingLook) this.pendingLook.heading = 0;
		this.heldHeading = 0;
		this.hold = 'seek';
	}

	/** Turn the orbit rigidly round the target, as a body's spin carries the
	 *  ground under it. A tilt goes along. */
	carry(rotation: Quaternion): void {
		const cam = this.object;
		const pos = this.looking ? this.orbitPos : cam.position;
		pos.sub(this.target).applyQuaternion(rotation).add(this.target);
		(this.looking ? this.orbitQuat : cam.quaternion).premultiply(rotation);
		if (this.looking) this.place();
	}

	/** Something else has the camera: the tilt ends where the view stands, and
	 *  the heading it leaves is the one held. */
	endLook(): void {
		this.looking = false;
		this.hold = 'soft';
		this.pendingLook = null;
		this.placedByName = false;
		this.stopGlide();
	}

	/** Drop the turn still to come. */
	private stopGlide(): void {
		this.glideHeading = 0;
		this.glideTilt = 0;
	}

	/** Whether the target has ground the view could tilt over: a drawn
	 *  surface, or one it stands on. */
	private groundKnown(): boolean {
		_n.subVectors(this.orbitPosition, this.target).normalize();
		return this.surfaceRadius(_n) !== null;
	}

	/** Let `move` shift the orbit, the tilt going along: a limit holds the
	 *  place the camera orbits, not the view's. */
	moveOrbit(move: (orbit: Vector3) => void): void {
		if (!this.looking) {
			move(this.object.position);
			return;
		}
		_hit.copy(this.orbitPos);
		move(this.orbitPos);
		if (this.orbitPos.equals(_hit)) return;
		this.aimOrbit();
		this.samplePivot();
		this.place();
	}

	/** A clamp pushed the camera off the ground. Where the orbit moved into
	 *  it, the orbit goes where the camera now stands, turned onto the same
	 *  ground, so the next frame does not put it back under. Where the ground
	 *  rose under a still view (its terrain refining), the push lasts as long
	 *  as that ground does. */
	adoptPlacement(): void {
		const orbitMoved = this.orbitMoved;
		this.orbitMoved = false;
		if (!this.looking) return;
		const cam = this.object;
		if (cam.position.equals(this.placedPos) && cam.quaternion.equals(this.placedQuat)) return;
		if (!orbitMoved) {
			this.placedPos.copy(cam.position);
			this.placedQuat.copy(cam.quaternion);
			return;
		}
		_n.subVectors(this.orbitPos, this.target).normalize();
		this.lookToward(_pivotGround.copy(_n).multiplyScalar(this.pivotRadius));
	}

	override update(deltaTime: number | null = null): boolean {
		const changed = this.step(deltaTime);
		const turned = this.keepHeading();
		return this.glide() || turned || changed;
	}

	/** Give a share of the turn a gesture asked for, as three's damping gives
	 *  the orbit's. True when that moved the camera. */
	private glide(): boolean {
		// Read as truthy: three's constructor updates before these fields are set.
		if (!this.glideHeading && !this.glideTilt) return false;
		const f = this.dampingFactor;
		this.turnNow(this.glideHeading * f, this.glideTilt * f);
		this.glideHeading *= 1 - f;
		this.glideTilt *= 1 - f;
		if (Math.abs(this.glideHeading) < GLIDE_DONE && Math.abs(this.glideTilt) < GLIDE_DONE) {
			this.stopGlide();
			this.onTurnSettled();
		}
		return true;
	}

	private step(deltaTime: number | null): boolean {
		if (!this.looking) {
			const changed = this.orbit(deltaTime);
			// The placement already reported this turn.
			if (this.pendingLook && this.groundKnown()) this.setLook(this.pendingLook);
			return changed;
		}
		const cam = this.object;
		if (!cam.position.equals(this.placedPos) || !cam.quaternion.equals(this.placedQuat)) {
			this.looking = false;
			this.stopGlide();
			return this.orbit(deltaTime);
		}
		if (!this.followGround()) return this.orbit(deltaTime);
		cam.position.copy(this.orbitPos);
		cam.quaternion.copy(this.orbitQuat);
		const changed = this.orbit(deltaTime);
		// Past rounding: three's own round trip moves the orbit by a few ulps.
		const moved = cam.position.distanceToSquared(this.orbitPos) > this.orbitPos.lengthSq() * 1e-20;
		if (moved) {
			this.orbitMoved = true;
			this.placedByName = false;
		}
		this.orbitPos.copy(cam.position);
		this.orbitQuat.copy(cam.quaternion);
		if (moved) this.samplePivot();
		// Out of reach of the ground the camera is back on the orbit pose.
		if (!this.holdAngles(this.lookShare())) {
			this.looking = false;
			return changed;
		}
		this.place();
		return changed;
	}

	/** Three's orbit, about the camera's own up: the camera always stands on
	 *  its orbit's equator, so it never reaches a pole. */
	private orbit(deltaTime: number | null): boolean {
		const cam = this.object;
		// Read as truthy: three's constructor updates before these fields are set.
		if (!this.orbitQuat) return super.update(deltaTime);
		_north.copy(cam.up);
		_from.subVectors(cam.position, this.target);
		_up.copy(_y).applyQuaternion(cam.quaternion);
		// Looking along its own up, the camera has no roll to keep: north stands in.
		if (_right.crossVectors(_up, _from).lengthSq() < _from.lengthSq() * 1e-12) _up.copy(_north);
		cam.up.copy(_up);
		const frame = this as unknown as OrbitFrame;
		frame._quat.setFromUnitVectors(_up, _y);
		frame._quatInverse.copy(frame._quat).invert();
		const changed = super.update(deltaTime);
		cam.up.copy(_north);
		// Not angleTo: its acos reads a still orbit as 1e-8 of travel.
		_to.subVectors(cam.position, this.target);
		this.travel = Math.atan2(_right.crossVectors(_from, _to).length(), _from.dot(_to));
		return changed;
	}

	/**
	 * Keep the heading as {@link hold} says, after the frame's orbit step.
	 * Anything other than the orbit that turned the view (a twist, a fly, a
	 * spin) sets the heading held. True when this turned the view.
	 */
	private keepHeading(): boolean {
		// Read as truthy: three's constructor updates before these fields are set.
		if (!this.orbitQuat || !this.enabled) return false;
		const heading = this.readHeading();
		if (heading === null) return false;
		this.lastHeading = heading;
		const error =
			MathUtils.euclideanModulo(this.heldHeading - heading + Math.PI, 2 * Math.PI) - Math.PI;
		let turn = 0;
		switch (this.hold) {
			case 'exact':
				turn = error;
				break;
			case 'seek': {
				const done = Math.abs(error) < SEEK_DONE;
				turn = done ? error : error * Math.min(1, SEEK_PER_DAMPING * this.dampingFactor);
				// North itself may still be turning to a new reference.
				if (done && this.northSettled) {
					this.hold = 'soft';
					this.onTurnSettled();
				}
				break;
			}
			case 'soft': {
				if (this.travel === 0) break;
				const c = this.northClarity;
				const offPole = MathUtils.smoothstep(c, NORTH_PULL_NONE, NORTH_PULL_FULL);
				const nearNorth =
					1 - MathUtils.smoothstep(Math.abs(heading), NORTH_HOLD_FULL, NORTH_HOLD_NONE);
				const reach = ((NORTH_PULL * this.travel) / c) * offPole * nearNorth;
				turn = MathUtils.clamp(-heading, -reach, reach);
			}
		}
		if (Math.abs(turn) < 1e-12) return false;
		this.roll(turn);
		this.lastHeading = heading + turn;
		return Math.abs(turn) > TURN_SEEN;
	}

	/** The heading off north, read about the line from the target to the
	 *  orbit. Null straight over a pole. */
	private readHeading(): number | null {
		_n.subVectors(this.orbitPosition, this.target);
		const range = _n.length();
		if (!(range > 0)) return null;
		_n.divideScalar(range);
		_north.copy(this.object.up).addScaledVector(_n, -this.object.up.dot(_n));
		this.northClarity = _north.length();
		if (this.northClarity < MIN_NORTH_CLARITY) return null;
		_up.copy(_y).applyQuaternion(this.looking ? this.orbitQuat : this.object.quaternion);
		return Math.atan2(_ray.crossVectors(_north, _up).dot(_n), _north.dot(_up));
	}

	/** Turn the view about the line from the target to the orbit. */
	private roll(angle: number): void {
		_n.subVectors(this.orbitPosition, this.target).normalize();
		_qRoll.setFromAxisAngle(_n, angle);
		if (!this.looking) {
			this.object.quaternion.premultiply(_qRoll);
			return;
		}
		this.orbitQuat.premultiply(_qRoll);
		this.place();
	}

	/** Aim the camera at the target, `heading` off north. Straight over a
	 *  pole, where north gives none, the view keeps its roll. */
	private faceHeading(heading: number): void {
		const cam = this.object;
		_n.subVectors(cam.position, this.target);
		const range = _n.length();
		if (!(range > 0)) return;
		_n.divideScalar(range);
		_north.copy(cam.up).addScaledVector(_n, -cam.up.dot(_n));
		const clear = _north.length() >= MIN_NORTH_CLARITY;
		if (!clear) _north.copy(_y).applyQuaternion(cam.quaternion);
		_look.lookAt(cam.position, this.target, _north);
		cam.quaternion.setFromRotationMatrix(_look);
		if (clear) cam.quaternion.premultiply(_qRoll.setFromAxisAngle(_n, heading));
	}

	/** Aim the orbit pose at the target again, keeping its roll. */
	private aimOrbit(): void {
		_up.copy(_y).applyQuaternion(this.orbitQuat);
		_look.lookAt(this.orbitPos, this.target, _up);
		this.orbitQuat.setFromRotationMatrix(_look);
	}

	override dispose(): void {
		super.dispose();
		this.canvas.removeEventListener('pointerdown', this.onLookDown);
		this.canvas.removeEventListener('mousedown', this.blockMiddle);
		this.canvas.removeEventListener('pointerdown', this.onCatch);
		this.endLookDrag();
	}

	_handleTouchStartDollyPan(event: TouchPoint): void {
		orbitHandlers._handleTouchStartDollyPan.call(this, event);
		const [a, b] = this.fingers();
		this.twoFinger.begin(a, b, this.enableRotate && this.lookShare() > 0);
	}

	_handleTouchMoveDollyPan(event: TouchPoint): void {
		const [a, b] = this.fingers();
		const step = this.twoFinger.move(a, b);
		// Held while undecided: three's pinch and pan read from where the
		// fingers came down, and catch up once the gesture is the map's.
		if (step.mode === 'undecided') return;
		const rate = TURN_PER_HEIGHT / (this.canvas.clientHeight || 1);
		if (step.mode === 'tilt') {
			if (this.enableRotate) this.turn(0, -step.down * rate);
			return;
		}
		orbitHandlers._handleTouchMoveDollyPan.call(this, event);
		// The map turns with the fingers.
		if (step.twist !== 0 && this.enableRotate) this.turn(step.twist, 0);
	}

	/** The two fingers on the canvas, in the order they came down. */
	private fingers(): [Point, Point] {
		const touch = this as unknown as TouchState;
		const [a, b] = touch._pointers;
		return [touch._pointerPositions[a], touch._pointerPositions[b]];
	}

	_handleMouseWheel(event: WheelEvent): void {
		// Keeping the ground put swings the orbit, which a host may have barred;
		// and ground seen at a graze would swing it far for a small zoom.
		const anchored =
			this.enableRotate &&
			this.groundAt(event.clientX, event.clientY, _anchor) &&
			-_ray.dot(_hit.copy(_anchor).normalize()) > SIN_MIN_ANCHOR_ELEVATION;
		orbitHandlers._handleMouseWheel.call(this, event);
		if (anchored) this.holdUnder(event.clientX, event.clientY, _anchor);
	}

	/** The ground under a pointer, from the target, on the sphere through the
	 *  ground below the camera. False where the pointer is off it. */
	private groundAt(x: number, y: number, out: Vector3): boolean {
		const cam = this.object;
		cam.updateMatrixWorld();
		const rect = this.canvas.getBoundingClientRect();
		_ray
			.set(((x - rect.left) / rect.width) * 2 - 1, -((y - rect.top) / rect.height) * 2 + 1, 0.5)
			.unproject(cam)
			.sub(cam.position)
			.normalize();
		return this.groundAlong(_from.subVectors(cam.position, this.target), _ray, out);
	}

	/** Where the ray from `from` along the unit `dir` meets the ground, both
	 *  from the target. False where it passes the ground by. */
	groundAlong(from: Vector3, dir: Vector3, out: Vector3): boolean {
		let radius = this.surfaceRadius(_n.copy(from).normalize());
		// The ground's height where the ray lands, not under its start.
		for (let pass = 0; pass < GROUND_PASSES; pass++) {
			if (!radius) return false;
			const b = from.dot(dir);
			const c = from.lengthSq() - radius * radius;
			const disc = b * b - c;
			if (c <= 0 || disc < 0 || b >= 0) return false;
			out.copy(from).addScaledVector(dir, -b - Math.sqrt(disc));
			radius = this.surfaceRadius(_n.copy(out).normalize());
		}
		return true;
	}

	/** Whether a camera at `from` may look on at `ground` as a tilted view,
	 *  both from the target: the tilt is one its height allows. */
	looksOver(from: Vector3, ground: Vector3): boolean {
		const n = _n.copy(ground).normalize();
		const radius = this.surfaceRadius(n);
		if (!radius) return false;
		const offset = _from.copy(from).addScaledVector(n, -radius);
		const range = offset.length();
		const share = this.shareAt(range / radius);
		return share > 0 && offset.dot(n) >= range * Math.cos(MAX_TILT * share);
	}

	/**
	 * The orientation {@link lookToward} gives a camera at `from` looking on
	 * at `ground`, both from the target: its right lies level over that
	 * ground, whatever north is. Straight down, where level says nothing, the
	 * camera keeps north up.
	 */
	lookPose(from: Vector3, ground: Vector3, out: Quaternion): Quaternion {
		const n = _n.copy(ground).normalize();
		const back = _from
			.copy(from)
			.addScaledVector(n, -(this.surfaceRadius(n) ?? 0))
			.normalize();
		const right = _right.crossVectors(n, back);
		if (right.lengthSq() < 1e-12) {
			_look.lookAt(from, _hit.copy(from).sub(back), this.object.up);
			return out.setFromRotationMatrix(_look);
		}
		right.normalize();
		_look.makeBasis(right, _ray.crossVectors(back, right), back);
		return out.setFromRotationMatrix(_look);
	}

	/** Turn the view so that the camera, where it stands, looks on at `ground`
	 *  from the target: the orbit goes over that ground, tilted off it. */
	lookToward(ground: Vector3): void {
		const cam = this.object;
		const n = _n.copy(ground).normalize();
		const radius = this.surfaceRadius(n) ?? 0;
		// From the ground the pivot stands on, so the camera stays where it is.
		const offset = _from.subVectors(cam.position, this.target).addScaledVector(n, -radius);
		const range = offset.length();
		if (!(range > 0)) return;
		offset.divideScalar(range);
		this.orbitPos.copy(this.target).addScaledVector(n, radius + range);
		this.pivotRadius = radius;
		this.tilt = Math.acos(MathUtils.clamp(offset.dot(n), -1, 1));
		// A tilt swings the camera to the orbit's screen-down. Straight above
		// the ground, the view keeps its roll.
		const level = offset.addScaledVector(n, -offset.dot(n));
		if (level.lengthSq() > 1e-12) _up.copy(level).negate();
		else _up.copy(_y).applyQuaternion(cam.quaternion);
		_look.lookAt(this.orbitPos, this.target, _up);
		this.orbitQuat.setFromRotationMatrix(_look);
		this.placedByName = false;
		this.looking = true;
		if (!this.holdAngles(this.lookShare())) {
			this.looking = false;
			return;
		}
		this.place();
		this.onTurnSettled();
	}

	/** Swing the orbit round the target until `anchor` is under the pointer. */
	private holdUnder(x: number, y: number, anchor: Vector3): void {
		const cam = this.object;
		for (let pass = 0; pass < ANCHOR_PASSES; pass++) {
			if (!this.groundAt(x, y, _hit)) return;
			_turnBack.setFromUnitVectors(_hit.normalize(), _ray.copy(anchor).normalize());
			const pos = this.looking ? this.orbitPos : cam.position;
			pos.sub(this.target).applyQuaternion(_turnBack).add(this.target);
			(this.looking ? this.orbitQuat : cam.quaternion).premultiply(_turnBack);
			if (!this.looking) continue;
			this.orbitMoved = true;
			this.samplePivot();
			this.place();
		}
	}

	/** Turn the heading and tilt the view by these angles, in radians: over
	 *  the next frames with damping, as the orbit moves, and at once without. */
	private turn(heading: number, tilt: number): void {
		if (!this.enableDamping) {
			this.turnNow(heading, tilt);
			return;
		}
		this.glideHeading += heading;
		this.glideTilt += tilt;
	}

	private turnNow(heading: number, tilt: number): void {
		const cam = this.object;
		if (heading !== 0) {
			this.roll(heading);
			this.heldHeading += heading;
		}
		if (tilt === 0) return;
		const share = this.lookShare();
		if (share === 0) return;
		if (!this.looking) {
			this.looking = true;
			this.tilt = 0;
			this.orbitPos.copy(cam.position);
			this.orbitQuat.copy(cam.quaternion);
			this.samplePivot();
		}
		this.tilt = Math.max(0, this.tilt + tilt);
		this.holdAngles(share);
		this.place();
	}

	/** Share of the full tilt the orbit's height allows. */
	private lookShare(): number {
		_n.subVectors(this.orbitPosition, this.target);
		const range = _n.length();
		const ground = range > 0 ? this.surfaceRadius(_n.divideScalar(range)) : null;
		return ground ? this.shareAt((range - ground) / ground) : 0;
	}

	/** {@link lookShare} at a height over the ground, in radii of it. */
	private shareAt(height: number): number {
		const t = MathUtils.clamp(
			(LOOK_NONE_HEIGHT - height) / (LOOK_NONE_HEIGHT - LOOK_FULL_HEIGHT),
			0,
			1
		);
		return t * t * (3 - 2 * t);
	}

	/** Hold the tilt within `share` of its range. False when none is left. */
	private holdAngles(share: number): boolean {
		this.tilt = Math.min(this.tilt, MAX_TILT * share);
		return share > 0;
	}

	/**
	 * Take up a change in the ground under the orbit. A view placed by name
	 * goes where its angles put it over the new ground. One the reader turned
	 * keeps the camera where it stands and turns onto the new ground, rather
	 * than jump as finer terrain loads. False when that leaves no tilt.
	 */
	private followGround(): boolean {
		_n.subVectors(this.orbitPos, this.target);
		const range = _n.length();
		const ground = range > 0 ? this.surfaceRadius(_n.divideScalar(range)) : null;
		if (ground === null) return true;
		const pivot = Math.min(ground, range);
		if (Math.abs(pivot - this.pivotRadius) <= ground * PIVOT_REFINE) return true;
		if (this.placedByName) {
			this.pivotRadius = pivot;
			return true;
		}
		this.lookToward(_pivotGround.copy(_n).multiplyScalar(ground));
		return this.looking;
	}

	/** Read the ground under the orbit. */
	private samplePivot(): void {
		_n.subVectors(this.orbitPos, this.target);
		const range = _n.length();
		const ground = range > 0 ? this.surfaceRadius(_n.divideScalar(range)) : 0;
		this.pivotRadius = Math.min(ground ?? 0, range);
	}

	/** Swing the orbit pose about the ground under the centre of the view. */
	private place(): void {
		const cam = this.object;
		_n.subVectors(this.orbitPos, this.target);
		const range = _n.length();
		if (range > 0) _n.divideScalar(range);
		_pivot.copy(this.target).addScaledVector(_n, Math.min(this.pivotRadius, range));
		_right.set(1, 0, 0).applyQuaternion(this.orbitQuat);
		_qTilt.setFromAxisAngle(_right, this.tilt);
		cam.position.copy(this.orbitPos).sub(_pivot).applyQuaternion(_qTilt).add(_pivot);
		cam.quaternion.multiplyQuaternions(_qTilt, this.orbitQuat);
		this.placedPos.copy(cam.position);
		this.placedQuat.copy(cam.quaternion);
	}

	/** A new touch or click catches the camera: what was gliding stops. */
	private readonly onCatch = (): void => {
		if (!this.glideHeading && !this.glideTilt) return;
		this.stopGlide();
		this.onTurnSettled();
	};

	private readonly blockMiddle = (event: MouseEvent): void => {
		if (event.button === 1) event.preventDefault();
	};

	private readonly onLookDown = (event: PointerEvent): void => {
		if (event.button !== 1 || event.pointerType !== 'mouse') return;
		event.preventDefault();
		if (!this.enabled || !this.enableRotate || this.dragPointer !== null) return;
		this.dragPointer = event.pointerId;
		this.dragX = event.clientX;
		this.dragY = event.clientY;
		const doc = this.canvas.ownerDocument;
		doc.addEventListener('pointermove', this.onLookMove);
		doc.addEventListener('pointerup', this.onLookUp);
		doc.addEventListener('pointercancel', this.onLookUp);
		this.dispatchEvent({ type: 'start' });
	};

	private readonly onLookMove = (event: PointerEvent): void => {
		if (event.pointerId !== this.dragPointer) return;
		if (!this.enabled || !this.enableRotate) return;
		const dx = event.clientX - this.dragX;
		const dy = event.clientY - this.dragY;
		this.dragX = event.clientX;
		this.dragY = event.clientY;
		const rate = TURN_PER_HEIGHT / (this.canvas.clientHeight || 1);
		// Grabs the ground below the pivot, where a tilted view shows it.
		if (dx !== 0 || dy !== 0) this.turn(-dx * rate, -dy * rate);
	};

	private readonly onLookUp = (event: PointerEvent): void => {
		if (event.pointerId !== this.dragPointer) return;
		this.endLookDrag();
		this.dispatchEvent({ type: 'end' });
	};

	private endLookDrag(): void {
		this.dragPointer = null;
		const doc = this.canvas.ownerDocument;
		doc.removeEventListener('pointermove', this.onLookMove);
		doc.removeEventListener('pointerup', this.onLookUp);
		doc.removeEventListener('pointercancel', this.onLookUp);
	}
}
