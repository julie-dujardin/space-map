import { VISIBILITY } from './thresholds';

export type VisibilityFlags = {
	groupVisible: boolean;
	orbitVisible: boolean;
	showLabel: boolean;
	isClose: boolean;
};

export function moonVisFlags(
	vis: VISIBILITY,
	hideCappedLabels: boolean,
	isFocused: boolean
): VisibilityFlags {
	const capped = vis === VISIBILITY.CAPPED;
	return {
		groupVisible:
			vis === VISIBILITY.CLOSE || vis === VISIBILITY.FULL || (capped && hideCappedLabels),
		// Focused body keeps orbit visible at CLOSE; applyLabelDisplay hides it when the sphere fills the screen.
		orbitVisible: vis === VISIBILITY.FULL || (vis === VISIBILITY.CLOSE && isFocused),
		showLabel: vis === VISIBILITY.FULL || (capped && hideCappedLabels),
		isClose: vis === VISIBILITY.CLOSE
	};
}

export function bodyVisFlags(
	vis: VISIBILITY,
	fullRendering: boolean,
	isFocused: boolean
): VisibilityFlags {
	return {
		// No FAR — mesh is sub-pixel at that distance, point cloud suffices.
		groupVisible: vis === VISIBILITY.CLOSE || vis === VISIBILITY.FULL,
		orbitVisible:
			(vis === VISIBILITY.FULL && fullRendering) || (vis === VISIBILITY.CLOSE && isFocused),
		showLabel: vis === VISIBILITY.FULL && fullRendering,
		isClose: fullRendering && vis === VISIBILITY.CLOSE
	};
}
