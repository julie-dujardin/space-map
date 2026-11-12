import { MathUtils, Matrix4, Quaternion, Vector3, type PerspectiveCamera } from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { TwoFingerGesture, type Point } from './two-finger';

/** Steepest tilt off the vertical. Short of the horizon, so the ground still
 *  fills the lower part of the view and the camera stays above it. */
export const MAX_TILT = MathUtils.degToRad(80);

/** Height over the ground, in radii, under which the view tilts and turns
 *  freely, and from which it does not at all: out in space a tilt only gets
 *  in the way of finding things. In between, the angles allowed shrink, and
 *  zooming back in does not give back what they lost. */
export const LOOK_FULL_HEIGHT = 0.5;
export const LOOK_NONE_HEIGHT = 1;

/** The view's turn off the orbit pose, in radians: `tilt` off the vertical
 *  toward the horizon, `heading` round the vertical. */
export interface LookAngles {
	tilt: number;
	heading: number;
}

export const LEVEL_LOOK: Readonly<LookAngles> = { tilt: 0, heading: 0 };

/** Middle-drag and two-finger turn rate: half a turn per viewport height. */
const TURN_PER_HEIGHT = Math.PI;

const _n = new Vector3();
const _right = new Vector3();
const _pivot = new Vector3();
const _qHeading = new Quaternion();
const _qTilt = new Quaternion();
const _ray = new Vector3();
const _from = new Vector3();
const _anchor = new Vector3();
const _hit = new Vector3();
const _turnBack = new Quaternion();
const _was = new Quaternion();
const _pivotGround = new Vector3();
const _look = new Matrix4();

/** Turn still to come, in radians, under which a glide is done. */
const GLIDE_DONE = 1e-5;

/** Passes that put the ground back under the pointer after a zoom. Each
 *  leaves the error of the roll the orbit's own up takes back out. */
const ANCHOR_PASSES = 3;

/** Least elevation of the pointer's ray over the ground for the wheel to keep
 *  that ground put, as three's own cursor zoom stops near the horizon. */
const SIN_MIN_ANCHOR_ELEVATION = Math.sin(MathUtils.degToRad(20));

/** Passes that find where a ray lands on relief, each from the last one's height. */
const GROUND_PASSES = 3;

/** A touch as three's handlers read it. */
interface TouchPoint {
	pointerId: number;
	pageX: number;
	pageY: number;
}

/** The handlers three keeps off its typings. */
interface PointerHandlers {
	_handleMouseDownRotate(event: { clientX: number; clientY: number }): void;
	_handleMouseMoveRotate(event: { clientX: number; clientY: number }): void;
	_handleTouchStartRotate(event: TouchPoint): void;
	_handleTouchMoveRotate(event: TouchPoint): void;
	_handleTouchStartDollyPan(event: TouchPoint): void;
	_handleTouchMoveDollyPan(event: TouchPoint): void;
	_handleMouseWheel(event: WheelEvent): void;
}
const orbitHandlers = OrbitControls.prototype as unknown as PointerHandlers;

/** The touch state three keeps off its typings. */
interface TouchState {
	_pointers: number[];
	_pointerPositions: Record<number, Point>;
	_getSecondPointerPosition(event: TouchPoint): { x: number; y: number };
}

/**
 * OrbitControls with a middle drag that tilts and turns the view about the
 * ground at its centre, the way a map does: up and down tilt it toward the
 * horizon, left and right turn the heading. On a touch screen two fingers
 * sliding up or down side by side tilt it, and a twist turns the heading
 * while they pinch and pan. With damping on, a tilt or a turn glides on
 * after the gesture, as the orbit does. The wheel keeps the ground under the
 * pointer where it is.
 *
 * The orbit underneath is unchanged, so a left drag and the wheel keep their
 * feel and carry the tilt along. Whatever else places the camera (a focus
 * change, a fly, a snap, a held pose) ends the tilt where it stands, so a
 * transition starts from the view on screen. A limit that holds the camera
 * holds the orbit with it.
 */
export class LookOrbitControls extends OrbitControls {
	declare object: PerspectiveCamera;
	private heading = 0;
	private tilt = 0;
	/** Whether the camera stands off the orbit pose below. */
	private looking = false;
	private readonly orbitPos = new Vector3();
	private readonly orbitQuat = new Quaternion();
	/** Height of the ground the view turns about, from the target. Read when
	 *  the orbit moves, not each frame: the drawn ground refines under a still
	 *  camera, and the view would drift with it. */
	private pivotRadius = 0;
	/** The up the orbit pose was last built on. */
	private readonly lastUp = new Vector3();
	/** The heading was given off north, by a link or a jump: it stays off
	 *  north while north turns. A turn the reader made, or one carried over
	 *  from another focus, holds its direction in space instead. */
	private holdsNorth = false;
	private northTurning = false;
	/** A turn placed before there was ground to turn over (a link opening
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
		 *  scene units; null for none, and no turn. */
		private readonly surfaceRadius: (direction: Vector3) => number | null,
		/** The turn settled where nobody's gesture put it: the view to report. */
		private readonly onTurnSettled: () => void = () => {}
	) {
		super(camera, canvas);
		this.mouseButtons.MIDDLE = null;
		this.addEventListener('start', () => (this.pendingLook = null));
		canvas.addEventListener('pointerdown', this.onLookDown);
		// Middle-button autoscroll and paste ride on mousedown.
		canvas.addEventListener('mousedown', this.blockMiddle);
		canvas.addEventListener('pointerdown', this.onCatch);
	}

	/** Where the orbit holds the camera, under any tilt. */
	get orbitPosition(): Vector3 {
		return this.looking ? this.orbitPos : this.object.position;
	}

	/** Whether the view stands turned off the orbit pose. */
	get turned(): boolean {
		return this.looking;
	}

	/** The view's turn as it stands, or as placed while it waits for ground. */
	get look(): LookAngles {
		if (this.looking) return { tilt: this.tilt, heading: this.heading };
		return { ...(this.pendingLook ?? LEVEL_LOOK) };
	}

	/** Turn the view off the orbit pose the camera is on, as far as its height
	 *  allows: a placement that names a view. */
	setLook({ tilt, heading }: LookAngles): void {
		const cam = this.object;
		this.looking = false;
		this.pendingLook = null;
		this.stopGlide();
		if (tilt === 0 && heading === 0) return;
		if (!this.groundKnown()) {
			this.pendingLook = { tilt, heading };
			return;
		}
		const share = this.lookShare();
		if (share === 0) return;
		this.orbitPos.copy(cam.position);
		_look.lookAt(this.orbitPos, this.target, cam.up);
		this.orbitQuat.setFromRotationMatrix(_look);
		this.samplePivot();
		this.lastUp.copy(cam.up);
		this.holdsNorth = true;
		this.tilt = MathUtils.clamp(tilt, 0, MAX_TILT);
		this.heading = heading;
		this.holdAngles(share);
		this.looking = true;
		this.place();
	}

	/** Turn a drag on screen into the orbit's axes, which the heading has turned
	 *  away from the screen's. */
	toOrbitAxes(x: number, y: number): [number, number] {
		if (!this.looking || this.heading === 0) return [x, y];
		const c = Math.cos(this.heading);
		const s = Math.sin(this.heading);
		return [c * x + s * y, c * y - s * x];
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

	/** Something else has the camera: the turn ends where the view stands. */
	endLook(): void {
		this.looking = false;
		this.pendingLook = null;
		this.stopGlide();
	}

	/** Drop the turn still to come. */
	private stopGlide(): void {
		this.glideHeading = 0;
		this.glideTilt = 0;
	}

	/** Whether the target has ground the view could turn over: a drawn
	 *  surface, or one it stands on. */
	private groundKnown(): boolean {
		_n.subVectors(this.orbitPosition, this.target).normalize();
		return this.surfaceRadius(_n) !== null;
	}

	/** Let `move` shift the orbit, the turn going along: a limit holds the
	 *  place the camera orbits, not the view's. */
	moveOrbit(move: (orbit: Vector3) => void): void {
		if (!this.looking) {
			move(this.object.position);
			return;
		}
		_hit.copy(this.orbitPos);
		move(this.orbitPos);
		if (this.orbitPos.equals(_hit)) return;
		_look.lookAt(this.orbitPos, this.target, this.object.up);
		this.orbitQuat.setFromRotationMatrix(_look);
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
		const holds = this.holdsNorth;
		_n.subVectors(this.orbitPos, this.target).normalize();
		this.lookToward(_pivotGround.copy(_n).multiplyScalar(this.pivotRadius));
		this.holdsNorth = holds;
	}

	override update(deltaTime: number | null = null): boolean {
		const changed = this.step(deltaTime);
		this.glide();
		return changed;
	}

	/** Give a share of the turn a gesture asked for, as three's damping gives
	 *  the orbit's. */
	private glide(): void {
		// Read as truthy: three's constructor updates before these fields are set.
		if (!this.glideHeading && !this.glideTilt) return;
		const f = this.dampingFactor;
		this.turnNow(this.glideHeading * f, this.glideTilt * f);
		this.glideHeading *= 1 - f;
		this.glideTilt *= 1 - f;
		if (Math.abs(this.glideHeading) < GLIDE_DONE && Math.abs(this.glideTilt) < GLIDE_DONE) {
			this.stopGlide();
			this.onTurnSettled();
		}
	}

	private step(deltaTime: number | null): boolean {
		if (!this.looking) {
			const changed = super.update(deltaTime);
			// The placement already reported this turn.
			if (this.pendingLook && this.groundKnown()) this.setLook(this.pendingLook);
			return changed;
		}
		const cam = this.object;
		if (!cam.position.equals(this.placedPos) || !cam.quaternion.equals(this.placedQuat)) {
			this.looking = false;
			this.stopGlide();
			return super.update(deltaTime);
		}
		cam.position.copy(this.orbitPos);
		cam.quaternion.copy(this.orbitQuat);
		_was.copy(this.orbitQuat);
		const changed = super.update(deltaTime);
		// Past rounding: three's own round trip moves the orbit by a few ulps.
		const moved = cam.position.distanceToSquared(this.orbitPos) > this.orbitPos.lengthSq() * 1e-20;
		if (moved) this.orbitMoved = true;
		this.orbitPos.copy(cam.position);
		this.orbitQuat.copy(cam.quaternion);
		if (moved) this.samplePivot();
		// A new north rolls the orbit pose under the view: the heading takes the
		// roll back, so the view keeps its direction while the compass turns.
		const northTurned = !cam.up.equals(this.lastUp);
		this.lastUp.copy(cam.up);
		// The bearing is read off north: once north rests, it is the view's again.
		if (this.northTurning && !northTurned) this.onTurnSettled();
		this.northTurning = northTurned;
		if (northTurned && !this.holdsNorth) {
			_n.subVectors(this.orbitPos, this.target).normalize();
			const before = _right.set(0, -1, 0).applyQuaternion(_was);
			const after = _hit.set(0, -1, 0).applyQuaternion(this.orbitQuat);
			this.heading += Math.atan2(_ray.crossVectors(after, before).dot(_n), after.dot(before));
		}
		// Out of reach of the ground the camera is back on the orbit pose.
		if (!this.holdAngles(this.lookShare())) {
			this.looking = false;
			return changed;
		}
		this.place();
		return changed;
	}

	override dispose(): void {
		super.dispose();
		this.canvas.removeEventListener('pointerdown', this.onLookDown);
		this.canvas.removeEventListener('mousedown', this.blockMiddle);
		this.canvas.removeEventListener('pointerdown', this.onCatch);
		this.endLookDrag();
	}

	_handleMouseDownRotate(event: PointerEvent): void {
		orbitHandlers._handleMouseDownRotate.call(this, this.rotated(event));
	}

	_handleMouseMoveRotate(event: PointerEvent): void {
		orbitHandlers._handleMouseMoveRotate.call(this, this.rotated(event));
	}

	_handleTouchStartRotate(event: TouchPoint): void {
		orbitHandlers._handleTouchStartRotate.call(this, this.rotatedTouch(event));
	}

	_handleTouchMoveRotate(event: TouchPoint): void {
		orbitHandlers._handleTouchMoveRotate.call(this, this.rotatedTouch(event));
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

	/** Whether a camera at `from` may look on at `ground` as a turned view,
	 *  both from the target: the turn is one its height allows. */
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
	 *  from the target: the orbit goes over that ground, turned off it. */
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
		this.lastUp.copy(cam.up);
		_look.lookAt(this.orbitPos, this.target, cam.up);
		this.orbitQuat.setFromRotationMatrix(_look);
		this.tilt = Math.acos(MathUtils.clamp(offset.dot(n), -1, 1));
		// A tilt swings the camera to the orbit's screen-down, then round n.
		const down = _right.set(0, -1, 0).applyQuaternion(this.orbitQuat);
		const level = offset.addScaledVector(n, -offset.dot(n));
		this.heading = Math.atan2(_ray.crossVectors(down, level).dot(n), down.dot(level));
		this.holdsNorth = false;
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
			// The orbit's own pose, as its next update would set it.
			_look.lookAt(pos, this.target, cam.up);
			(this.looking ? this.orbitQuat : cam.quaternion).setFromRotationMatrix(_look);
			if (!this.looking) continue;
			this.orbitMoved = true;
			this.samplePivot();
			this.place();
		}
	}

	/** A drag in the orbit's axes moves the ground the way the pointer goes. */
	private rotated(event: PointerEvent): { clientX: number; clientY: number } {
		const [clientX, clientY] = this.toOrbitAxes(event.clientX, event.clientY);
		return { clientX, clientY };
	}

	/** The same for a touch. With two fingers three drags their midpoint, and
	 *  reads the other finger itself: this one stands where it makes that
	 *  midpoint the turned one. */
	private rotatedTouch(event: TouchPoint): TouchPoint {
		const touch = this as unknown as TouchState;
		if (touch._pointers.length === 1) {
			const [pageX, pageY] = this.toOrbitAxes(event.pageX, event.pageY);
			return { pointerId: event.pointerId, pageX, pageY };
		}
		const other = touch._getSecondPointerPosition(event);
		const [x, y] = this.toOrbitAxes((event.pageX + other.x) / 2, (event.pageY + other.y) / 2);
		return { pointerId: event.pointerId, pageX: 2 * x - other.x, pageY: 2 * y - other.y };
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
		const share = this.lookShare();
		if (share === 0) return;
		if (!this.looking) {
			this.looking = true;
			this.heading = 0;
			this.tilt = 0;
			this.orbitPos.copy(cam.position);
			this.orbitQuat.copy(cam.quaternion);
			this.samplePivot();
			this.lastUp.copy(cam.up);
		}
		this.holdsNorth = false;
		this.heading += heading;
		this.tilt = Math.max(0, this.tilt + tilt);
		this.holdAngles(share);
		this.place();
	}

	/** Share of the full tilt and heading the orbit's height allows. */
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

	/** Hold the angles within `share` of their range. False when none is left. */
	private holdAngles(share: number): boolean {
		this.tilt = Math.min(this.tilt, MAX_TILT * share);
		this.heading = MathUtils.euclideanModulo(this.heading + Math.PI, 2 * Math.PI) - Math.PI;
		this.heading = MathUtils.clamp(this.heading, -Math.PI * share, Math.PI * share);
		return share > 0;
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
		_qHeading.setFromAxisAngle(_n, this.heading);
		_qTilt.setFromAxisAngle(_right, this.tilt);
		_qHeading.multiply(_qTilt);
		cam.position.copy(this.orbitPos).sub(_pivot).applyQuaternion(_qHeading).add(_pivot);
		cam.quaternion.multiplyQuaternions(_qHeading, this.orbitQuat);
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
		if (this.lookShare() === 0) return;
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
