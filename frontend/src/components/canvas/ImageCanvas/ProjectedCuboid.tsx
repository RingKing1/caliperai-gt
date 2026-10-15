import React, { useMemo } from 'react';
import { Line, Group, Text } from 'react-konva';
import { DASH_PATTERN } from '@/constants';
import {
  getCuboidCorners,
  CUBOID_EDGES,
  projectLidarPointsToImage,
  projectLidarPointToImageWithDebug,
  isCuboidVisibleInCameraLidarFrame,
} from '@/utils/projection';
import type { CuboidData, Point2D, SceneCalibration } from '@/types';

export interface ProjectedCuboidProps {
  cuboid: CuboidData;
  classColor: string;
  calibration: SceneCalibration;
  cameraId: string;
  imageSize: { width: number; height: number };
  isAutoAnnotation: boolean;
  isVerified: boolean;
  isSelected?: boolean;
  showDebugInfo?: boolean;
}

export const ProjectedCuboid: React.FC<ProjectedCuboidProps> = ({
  cuboid,
  classColor,
  calibration,
  cameraId,
  imageSize,
  isAutoAnnotation,
  isVerified,
  isSelected = false,
  showDebugInfo = false,
}) => {
  const { projectedEdges, frontFaceCorners, debugInfo, isVisible } = useMemo(() => {
    const cameraCalib = calibration.lidar_to_cameras[cameraId];

    if (!cameraCalib) {
      return { projectedEdges: [], frontFaceCorners: [], debugInfo: null, isVisible: false };
    }

    const visible = isCuboidVisibleInCameraLidarFrame(
      cuboid,
      cameraCalib.extrinsic,
      cameraCalib.intrinsic,
      imageSize,
      4,
      cameraId
    );

    if (!visible) {
      return { projectedEdges: [], frontFaceCorners: [], debugInfo: null, isVisible: false };
    }

    const lidarCorners = getCuboidCorners(cuboid);

    const corners2D = projectLidarPointsToImage(
      lidarCorners,
      cameraCalib.extrinsic,
      cameraCalib.intrinsic,
      imageSize
    );

    const centerDebug = projectLidarPointToImageWithDebug(
      cuboid.center,
      cameraCalib.extrinsic,
      cameraCalib.intrinsic,
      imageSize
    );

    const edges: { start: Point2D; end: Point2D }[] = [];
    for (const [i, j] of CUBOID_EDGES) {
      const start = corners2D[i];
      const end = corners2D[j];
      if (start && end) {
        edges.push({ start, end });
      }
    }

    const c0 = corners2D[0];
    const c1 = corners2D[1];
    const c5 = corners2D[5];
    const c4 = corners2D[4];
    const frontFaceCorners: Point2D[] = (c0 && c1 && c5 && c4) ? [c0, c1, c5, c4] : [];

    const debugInfo = {
      lidar: centerDebug.lidarPoint,
      camera: centerDebug.cameraPoint,
      image2D: centerDebug.imagePoint
    };

    return { projectedEdges: edges, frontFaceCorners, debugInfo, isVisible: true };
  }, [cuboid, calibration, cameraId, imageSize]);

  if (!isVisible || projectedEdges.length === 0) {
    return null;
  }

  const dash = isAutoAnnotation && !isVerified ? DASH_PATTERN : undefined;

  return (
    <Group>
      {isSelected && frontFaceCorners.length === 4 && (
        <Line
          points={[
            frontFaceCorners[0].x, frontFaceCorners[0].y,
            frontFaceCorners[1].x, frontFaceCorners[1].y,
            frontFaceCorners[2].x, frontFaceCorners[2].y,
            frontFaceCorners[3].x, frontFaceCorners[3].y,
          ]}
          closed={true}
          fill="rgba(250, 204, 21, 0.35)"
        />
      )}
      {projectedEdges.map((edge, i) => (
        <Line
          key={i}
          points={[edge.start.x, edge.start.y, edge.end.x, edge.end.y]}
          stroke={isSelected ? '#facc15' : (isVerified ? '#ef4444' : classColor)}
          strokeWidth={isSelected ? 3 : 2}
          dash={dash}
          opacity={isSelected ? 1.0 : 0.8}
        />
      ))}

      {/* Debug info overlay */}
      {showDebugInfo && debugInfo && debugInfo.image2D && (
        <Group>
          <Text
            x={debugInfo.image2D.x + 5}
            y={debugInfo.image2D.y - 45}
            text={`LiDAR: (${debugInfo.lidar.x.toFixed(2)}, ${debugInfo.lidar.y.toFixed(2)}, ${debugInfo.lidar.z.toFixed(2)})`}
            fontSize={10}
            fill="orange"
            stroke="black"
            strokeWidth={0.5}
          />
          <Text
            x={debugInfo.image2D.x + 5}
            y={debugInfo.image2D.y - 30}
            text={`Camera: (${debugInfo.camera.x.toFixed(2)}, ${debugInfo.camera.y.toFixed(2)}, ${debugInfo.camera.z.toFixed(2)})`}
            fontSize={10}
            fill="magenta"
            stroke="black"
            strokeWidth={0.5}
          />
          <Text
            x={debugInfo.image2D.x + 5}
            y={debugInfo.image2D.y - 15}
            text={`2D: (${debugInfo.image2D.x.toFixed(1)}, ${debugInfo.image2D.y.toFixed(1)})`}
            fontSize={10}
            fill="yellow"
            stroke="black"
            strokeWidth={0.5}
          />
        </Group>
      )}
    </Group>
  );
};

export default ProjectedCuboid;
