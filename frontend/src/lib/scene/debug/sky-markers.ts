import { Group, type Scene } from 'three';
import {
	createSkyDebugMarkers,
	disposeSkyDebugMarkers
} from '$lib/scene/objects/sky/debug-markers';

/** Celestial-landmark debug markers (galactic center, NCP, …). Lazy build, full teardown on hide. */
export class SkyDebugMarkers {
	private group: Group | null = null;

	constructor(private readonly scene: Scene) {}

	setVisible(visible: boolean): void {
		if (visible) {
			if (!this.group) {
				this.group = createSkyDebugMarkers();
				this.scene.add(this.group);
			}
			this.group.visible = true;
		} else if (this.group) {
			disposeSkyDebugMarkers(this.group);
			this.group = null;
		}
	}
}
