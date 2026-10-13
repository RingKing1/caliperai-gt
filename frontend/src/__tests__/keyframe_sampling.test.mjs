import test, { describe } from 'node:test';
import assert from 'node:assert/strict';

// Core math logic matching editorStore implementation
function createKeyframeHelper(keyframeSamplingEnabled, keyframeInterval, keyframeStartFrame, totalFrames) {
  const isKeyframeAt = (index) => {
    if (!keyframeSamplingEnabled || totalFrames === 0) return false;
    if (index < keyframeStartFrame) return false;
    return (index - keyframeStartFrame) % Math.max(1, keyframeInterval) === 0;
  };

  const getNextKeyframeIndex = (currentIndex) => {
    if (totalFrames === 0) return null;
    const interval = Math.max(1, keyframeInterval);
    if (currentIndex < keyframeStartFrame) {
      return Math.min(totalFrames - 1, keyframeStartFrame);
    }
    const offset = currentIndex - keyframeStartFrame;
    const nextOffset = (Math.floor(offset / interval) + 1) * interval;
    const target = keyframeStartFrame + nextOffset;
    return target < totalFrames ? target : null;
  };

  const getPrevKeyframeIndex = (currentIndex) => {
    if (totalFrames === 0 || currentIndex <= keyframeStartFrame) return null;
    const interval = Math.max(1, keyframeInterval);
    const offset = currentIndex - keyframeStartFrame;
    const prevOffset = (offset % interval === 0)
      ? offset - interval
      : Math.floor(offset / interval) * interval;
    const target = keyframeStartFrame + prevOffset;
    return target >= 0 ? target : null;
  };

  return { isKeyframeAt, getNextKeyframeIndex, getPrevKeyframeIndex };
}

describe('Keyframe Sampling Logic Tests', () => {
  test('Standard 10-frame interval starting at frame 0', () => {
    const helper = createKeyframeHelper(true, 10, 0, 100);

    // Keyframe verification
    assert.equal(helper.isKeyframeAt(0), true);
    assert.equal(helper.isKeyframeAt(1), false);
    assert.equal(helper.isKeyframeAt(9), false);
    assert.equal(helper.isKeyframeAt(10), true);
    assert.equal(helper.isKeyframeAt(20), true);
    assert.equal(helper.isKeyframeAt(90), true);

    // Forward navigation
    assert.equal(helper.getNextKeyframeIndex(0), 10);
    assert.equal(helper.getNextKeyframeIndex(5), 10);
    assert.equal(helper.getNextKeyframeIndex(10), 20);
    assert.equal(helper.getNextKeyframeIndex(90), null); // out of range

    // Backward navigation
    assert.equal(helper.getPrevKeyframeIndex(0), null);
    assert.equal(helper.getPrevKeyframeIndex(5), 0);
    assert.equal(helper.getPrevKeyframeIndex(10), 0);
    assert.equal(helper.getPrevKeyframeIndex(15), 10);
    assert.equal(helper.getPrevKeyframeIndex(20), 10);
  });

  test('Custom offset starting at frame 5 with interval 10', () => {
    const helper = createKeyframeHelper(true, 10, 5, 50);

    // Keyframe verification
    assert.equal(helper.isKeyframeAt(0), false);
    assert.equal(helper.isKeyframeAt(4), false);
    assert.equal(helper.isKeyframeAt(5), true);
    assert.equal(helper.isKeyframeAt(15), true);
    assert.equal(helper.isKeyframeAt(25), true);
    assert.equal(helper.isKeyframeAt(35), true);
    assert.equal(helper.isKeyframeAt(45), true);

    // Forward from before start
    assert.equal(helper.getNextKeyframeIndex(0), 5);
    assert.equal(helper.getNextKeyframeIndex(2), 5);
    assert.equal(helper.getNextKeyframeIndex(5), 15);
    assert.equal(helper.getNextKeyframeIndex(15), 25);

    // Backward
    assert.equal(helper.getPrevKeyframeIndex(0), null);
    assert.equal(helper.getPrevKeyframeIndex(5), null);
    assert.equal(helper.getPrevKeyframeIndex(10), 5);
    assert.equal(helper.getPrevKeyframeIndex(15), 5);
    assert.equal(helper.getPrevKeyframeIndex(25), 15);
  });

  test('Sampling disabled returns false', () => {
    const helper = createKeyframeHelper(false, 10, 0, 100);
    assert.equal(helper.isKeyframeAt(0), false);
    assert.equal(helper.isKeyframeAt(10), false);
  });
});

describe('Box-Local Arrow Navigation Unit Tests', () => {
  function computeWorldDelta(key, currentView, yaw, moveStep = 0.1) {
    let screenDx = 0, screenDy = 0;
    if (key === 'arrowright') screenDx = moveStep;
    else if (key === 'arrowleft') screenDx = -moveStep;
    else if (key === 'arrowup') screenDy = moveStep;
    else if (key === 'arrowdown') screenDy = -moveStep;

    let localDx = 0, localDy = 0, localDz = 0;
    if (currentView === 'top') {
      localDx = screenDx;
      localDy = screenDy;
    } else if (currentView === 'side') {
      localDx = screenDx;
      localDz = screenDy;
    } else if (currentView === 'front') {
      localDy = -screenDx;
      localDz = screenDy;
    }

    const cos = Math.cos(yaw);
    const sin = Math.sin(yaw);

    const worldDx = localDx * cos - localDy * sin;
    const worldDy = localDx * sin + localDy * cos;
    const worldDz = localDz;
    const fixZero = (v) => {
      const rounded = Math.round(v * 100) / 100;
      return Object.is(rounded, -0) ? 0 : rounded;
    };
    return {
      worldDx: fixZero(worldDx),
      worldDy: fixZero(worldDy),
      worldDz: fixZero(worldDz),
    };
  }

  test('Top view with heading = 0 rad (facing +X): right moves +X, up moves +Y', () => {
    const right = computeWorldDelta('arrowright', 'top', 0);
    assert.equal(Math.round(right.worldDx * 100) / 100, 0.1);
    assert.equal(Math.round(right.worldDy * 100) / 100, 0.0);

    const up = computeWorldDelta('arrowup', 'top', 0);
    assert.equal(Math.round(up.worldDx * 100) / 100, 0.0);
    assert.equal(Math.round(up.worldDy * 100) / 100, 0.1);
  });

  test('Top view with heading = 90 deg (facing +Y): right moves +Y, up moves -X', () => {
    const yaw = Math.PI / 2;
    const right = computeWorldDelta('arrowright', 'top', yaw);
    assert.equal(Math.round(right.worldDx * 100) / 100, 0.0);
    assert.equal(Math.round(right.worldDy * 100) / 100, 0.1); // along heading

    const up = computeWorldDelta('arrowup', 'top', yaw);
    assert.equal(Math.round(up.worldDx * 100) / 100, -0.1); // left of heading
    assert.equal(Math.round(up.worldDy * 100) / 100, 0.0);
  });

  test('Top view with heading = 180 deg (facing -X): right moves -X, up moves -Y', () => {
    const yaw = Math.PI;
    const right = computeWorldDelta('arrowright', 'top', yaw);
    assert.equal(Math.round(right.worldDx * 100) / 100, -0.1);
    assert.equal(Math.round(right.worldDy * 100) / 100, 0.0);

    const up = computeWorldDelta('arrowup', 'top', yaw);
    assert.equal(Math.round(up.worldDx * 100) / 100, 0.0);
    assert.equal(Math.round(up.worldDy * 100) / 100, -0.1);
  });
});
