import test, { describe } from 'node:test';
import assert from 'node:assert/strict';

// Helper function mirroring validateTrackBinding
function validateTrackBinding({
  targetTrackId,
  candidateAnnotation,
  allAnnotations,
  targetFrameId = candidateAnnotation.frame_id,
  frames = [],
  lockedAnnotationIds = new Set(),
}) {
  if (!targetTrackId) {
    return { valid: false, error: '目标轨迹 ID 不能为空' };
  }

  if (lockedAnnotationIds.has(candidateAnnotation.id)) {
    return { valid: false, error: '该标注已通过 QA 审核并锁定，禁止更改轨迹关联！' };
  }

  const annList = allAnnotations instanceof Map ? Array.from(allAnnotations.values()) : allAnnotations;

  const existingTrackAnns = annList.filter(
    (a) => a.track_id === targetTrackId && a.id !== candidateAnnotation.id
  );

  // 1. Hard Constraint: Temporal Exclusivity (One Object Per Frame Per Track)
  const conflictingAnn = existingTrackAnns.find((a) => a.frame_id === targetFrameId);
  if (conflictingAnn) {
    const fObj = frames.find((f) => f.id === targetFrameId);
    const frameLabel = fObj ? `第 ${fObj.frame_index + 1} 帧` : targetFrameId;
    return {
      valid: false,
      error: `轨迹冲突：目标轨迹在 ${frameLabel} 已存在标注物体。同一时刻一条轨迹有且仅能绑定一个物体！`,
      conflictingAnnotationId: conflictingAnn.id,
    };
  }

  // 2. Hard Constraint: Class Invariance (Category Consistency)
  if (existingTrackAnns.length > 0) {
    const trackClassId = existingTrackAnns[0].class_id;
    if (trackClassId && candidateAnnotation.class_id && trackClassId !== candidateAnnotation.class_id) {
      return {
        valid: false,
        error: `类别冲突：当前物体类别为 [${candidateAnnotation.class_id}]，而目标轨迹的类别为 [${trackClassId}]。同一轨迹内所有帧的物体类别必须严格一致！`,
      };
    }
  }

  // 3. Soft Constraints: Dimensions & Kinematics
  let warning;
  const candidateCuboid = candidateAnnotation.type === 'cuboid' ? candidateAnnotation.data : null;
  const trackCuboids = existingTrackAnns.filter((a) => a.type === 'cuboid' && a.data).map((a) => a.data);

  if (candidateCuboid && trackCuboids.length > 0) {
    const avgL = trackCuboids.reduce((acc, c) => acc + c.dimensions.length, 0) / trackCuboids.length;
    const avgW = trackCuboids.reduce((acc, c) => acc + c.dimensions.width, 0) / trackCuboids.length;
    const avgH = trackCuboids.reduce((acc, c) => acc + c.dimensions.height, 0) / trackCuboids.length;

    const cDims = candidateCuboid.dimensions;
    const diffL = Math.abs(cDims.length - avgL);
    const diffW = Math.abs(cDims.width - avgW);
    const diffH = Math.abs(cDims.height - avgH);
    const maxRatio = Math.max(diffL / avgL, diffW / avgW, diffH / avgH);

    if (maxRatio > 0.25 || diffL > 0.5 || diffW > 0.4 || diffH > 0.4) {
      warning = `尺寸突变提醒：当前物体尺寸偏差达 ${(maxRatio * 100).toFixed(0)}%`;
    }

    if (frames.length > 0 && candidateCuboid.center) {
      const frameIndexMap = new Map();
      frames.forEach((f) => frameIndexMap.set(f.id, f.frame_index));
      const candIdx = frameIndexMap.get(targetFrameId);

      if (candIdx !== undefined) {
        let minFrameDiff = Infinity;
        let closestAnn = null;
        for (const ann of existingTrackAnns) {
          const idx = frameIndexMap.get(ann.frame_id);
          if (idx !== undefined) {
            const diff = Math.abs(idx - candIdx);
            if (diff < minFrameDiff) {
              minFrameDiff = diff;
              closestAnn = ann;
            }
          }
        }

        if (closestAnn && closestAnn.type === 'cuboid' && minFrameDiff <= 2) {
          const closestCenter = closestAnn.data.center;
          const candCenter = candidateCuboid.center;
          const dist = Math.hypot(
            candCenter.x - closestCenter.x,
            candCenter.y - closestCenter.y,
            candCenter.z - closestCenter.z
          );
          const maxAllowed = 12.0 * minFrameDiff;
          if (dist > maxAllowed) {
            const warnMsg = `时空跳变提醒：空间位移高达 ${dist.toFixed(1)}m`;
            warning = warning ? `${warning} ${warnMsg}` : warnMsg;
          }
        }
      }
    }
  }

  return { valid: true, warning };
}

function validateTrackMerge({
  sourceTrackId,
  targetTrackId,
  allAnnotations,
}) {
  if (!sourceTrackId || !targetTrackId) {
    return { valid: false, error: '源轨迹 ID 或目标轨迹 ID 不能为空' };
  }
  if (sourceTrackId === targetTrackId) {
    return { valid: false, error: '无法将轨迹合并到自身' };
  }

  const annList = allAnnotations instanceof Map ? Array.from(allAnnotations.values()) : allAnnotations;
  const srcAnns = annList.filter((a) => a.track_id === sourceTrackId);
  const tgtAnns = annList.filter((a) => a.track_id === targetTrackId);

  const srcClass = srcAnns[0]?.class_id;
  const tgtClass = tgtAnns[0]?.class_id;

  if (srcClass && tgtClass && srcClass !== tgtClass) {
    return {
      valid: false,
      error: `类别不匹配：源轨迹类别为 [${srcClass}]，而目标轨迹类别为 [${tgtClass}]，禁止合并不同类别的轨迹！`,
    };
  }

  const targetFrameSet = new Set(tgtAnns.map((a) => a.frame_id).filter(Boolean));
  const overlappingFrameIds = [];
  srcAnns.forEach((a) => {
    if (a.frame_id && targetFrameSet.has(a.frame_id)) {
      overlappingFrameIds.push(a.frame_id);
    }
  });

  return {
    valid: true,
    overlappingCount: overlappingFrameIds.length,
    overlappingFrameIds,
  };
}

describe('Track Association & Validation Unit Tests', () => {
  const frames = [
    { id: 'f0', frame_index: 0 },
    { id: 'f1', frame_index: 1 },
    { id: 'f2', frame_index: 2 },
    { id: 'f3', frame_index: 3 },
  ];

  test('Constraint 1: Temporal Exclusivity - Reject same-frame duplicate assignment', () => {
    const allAnnotations = new Map([
      ['ann-1', { id: 'ann-1', frame_id: 'f0', track_id: 'trk-100', class_id: 'car' }],
    ]);

    const candidate = { id: 'ann-2', frame_id: 'f0', class_id: 'car' };

    const res = validateTrackBinding({
      targetTrackId: 'trk-100',
      candidateAnnotation: candidate,
      allAnnotations,
      frames,
    });

    assert.equal(res.valid, false);
    assert.match(res.error, /同一时刻一条轨迹有且仅能绑定一个物体/);
    assert.equal(res.conflictingAnnotationId, 'ann-1');
  });

  test('Constraint 1: Temporal Exclusivity - Allow assignment to different frame', () => {
    const allAnnotations = new Map([
      ['ann-1', { id: 'ann-1', frame_id: 'f0', track_id: 'trk-100', class_id: 'car' }],
    ]);

    const candidate = { id: 'ann-2', frame_id: 'f1', class_id: 'car' };

    const res = validateTrackBinding({
      targetTrackId: 'trk-100',
      candidateAnnotation: candidate,
      allAnnotations,
      frames,
    });

    assert.equal(res.valid, true);
    assert.equal(res.error, undefined);
  });

  test('Constraint 2: Class Invariance - Reject mismatched category', () => {
    const allAnnotations = new Map([
      ['ann-1', { id: 'ann-1', frame_id: 'f0', track_id: 'trk-100', class_id: 'car' }],
    ]);

    const candidate = { id: 'ann-2', frame_id: 'f1', class_id: 'pedestrian' };

    const res = validateTrackBinding({
      targetTrackId: 'trk-100',
      candidateAnnotation: candidate,
      allAnnotations,
      frames,
    });

    assert.equal(res.valid, false);
    assert.match(res.error, /类别冲突/);
  });

  test('Constraint 3: Rigid Body Dimensions - Warn on large size discrepancy', () => {
    const allAnnotations = new Map([
      ['ann-1', {
        id: 'ann-1',
        frame_id: 'f0',
        track_id: 'trk-100',
        class_id: 'car',
        type: 'cuboid',
        data: { dimensions: { length: 4.5, width: 2.0, height: 1.6 }, center: { x: 0, y: 0, z: 0 } },
      }],
    ]);

    // Candidate has 7.5m length (truck size) on a car track
    const candidate = {
      id: 'ann-2',
      frame_id: 'f1',
      class_id: 'car',
      type: 'cuboid',
      data: { dimensions: { length: 7.5, width: 2.5, height: 2.8 }, center: { x: 2, y: 0, z: 0 } },
    };

    const res = validateTrackBinding({
      targetTrackId: 'trk-100',
      candidateAnnotation: candidate,
      allAnnotations,
      frames,
    });

    assert.equal(res.valid, true);
    assert.ok(res.warning);
    assert.match(res.warning, /尺寸突变提醒/);
  });

  test('Constraint 4: Kinematic Sanity - Warn on teleportation jump', () => {
    const allAnnotations = new Map([
      ['ann-1', {
        id: 'ann-1',
        frame_id: 'f0',
        track_id: 'trk-100',
        class_id: 'car',
        type: 'cuboid',
        data: { dimensions: { length: 4.5, width: 2.0, height: 1.6 }, center: { x: 0, y: 0, z: 0 } },
      }],
    ]);

    // Candidate is 50 meters away in just 1 frame (0.1s -> 1800 km/h)
    const candidate = {
      id: 'ann-2',
      frame_id: 'f1',
      class_id: 'car',
      type: 'cuboid',
      data: { dimensions: { length: 4.5, width: 2.0, height: 1.6 }, center: { x: 50, y: 0, z: 0 } },
    };

    const res = validateTrackBinding({
      targetTrackId: 'trk-100',
      candidateAnnotation: candidate,
      allAnnotations,
      frames,
    });

    assert.equal(res.valid, true);
    assert.ok(res.warning);
    assert.match(res.warning, /时空跳变提醒/);
  });

  test('Constraint 5: QA Lock Protection - Reject editing locked annotation', () => {
    const allAnnotations = new Map();
    const candidate = { id: 'ann-locked', frame_id: 'f1', class_id: 'car' };

    const res = validateTrackBinding({
      targetTrackId: 'trk-100',
      candidateAnnotation: candidate,
      allAnnotations,
      lockedAnnotationIds: new Set(['ann-locked']),
    });

    assert.equal(res.valid, false);
    assert.match(res.error, /审核并锁定/);
  });

  test('Constraint 6: Merge Validation - Reject self-merge & class mismatch, detect overlapping frames', () => {
    const allAnnotations = new Map([
      ['ann-1', { id: 'ann-1', frame_id: 'f0', track_id: 'trk-1', class_id: 'car' }],
      ['ann-2', { id: 'ann-2', frame_id: 'f1', track_id: 'trk-1', class_id: 'car' }],
      ['ann-3', { id: 'ann-3', frame_id: 'f1', track_id: 'trk-2', class_id: 'car' }],
      ['ann-4', { id: 'ann-4', frame_id: 'f2', track_id: 'trk-2', class_id: 'car' }],
      ['ann-5', { id: 'ann-5', frame_id: 'f3', track_id: 'trk-ped', class_id: 'pedestrian' }],
    ]);

    // 1. Self merge
    const selfRes = validateTrackMerge({ sourceTrackId: 'trk-1', targetTrackId: 'trk-1', allAnnotations });
    assert.equal(selfRes.valid, false);
    assert.match(selfRes.error, /合并到自身/);

    // 2. Class mismatch
    const classRes = validateTrackMerge({ sourceTrackId: 'trk-ped', targetTrackId: 'trk-1', allAnnotations });
    assert.equal(classRes.valid, false);
    assert.match(classRes.error, /类别不匹配/);

    // 3. Overlap detection
    const mergeRes = validateTrackMerge({ sourceTrackId: 'trk-2', targetTrackId: 'trk-1', allAnnotations });
    assert.equal(mergeRes.valid, true);
    assert.equal(mergeRes.overlappingCount, 1);
    assert.deepEqual(mergeRes.overlappingFrameIds, ['f1']);
  });
});
