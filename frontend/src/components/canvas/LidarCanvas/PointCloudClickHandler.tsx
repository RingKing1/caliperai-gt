import React, { useCallback, useEffect, useRef } from 'react';
import { useThree } from '@react-three/fiber';
import * as THREE from 'three';
import type { Point3D } from '@/types';

interface PointCloudClickHandlerProps {
  onPointClick?: (point: Point3D) => void;
  onEmptyClick?: () => void;
}

export const PointCloudClickHandler: React.FC<PointCloudClickHandlerProps> = ({ onPointClick, onEmptyClick }) => {
  const { scene, camera, gl } = useThree();
  const pointerDownPos = useRef<{ x: number; y: number } | null>(null);

  const handlePointerDown = useCallback((e: PointerEvent) => {
    pointerDownPos.current = { x: e.clientX, y: e.clientY };
  }, []);

  const handleClick = useCallback(
    (e: MouseEvent) => {
      if (!onPointClick && !onEmptyClick) return;

      if (e.detail !== 1) return;

      if (pointerDownPos.current) {
        const dx = e.clientX - pointerDownPos.current.x;
        const dy = e.clientY - pointerDownPos.current.y;
        if (dx * dx + dy * dy > 9) return;
      }

      const canvas = gl.domElement;
      const rect = canvas.getBoundingClientRect();
      const ndcX = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      const ndcY = -((e.clientY - rect.top) / rect.height) * 2 + 1;

      const raycaster = new THREE.Raycaster();
      raycaster.params.Points = { threshold: 0.3 };
      raycaster.setFromCamera(new THREE.Vector2(ndcX, ndcY), camera);

      const pointObjects: THREE.Object3D[] = [];
      const meshObjects: THREE.Object3D[] = [];
      scene.traverse((obj) => {
        if ((obj as THREE.Points).isPoints) {
          pointObjects.push(obj);
        } else if (
          (obj as THREE.Mesh).isMesh &&
          (obj as THREE.Mesh).geometry?.type === 'BoxGeometry'
        ) {
          // Only cuboid boxes count as annotation hits here (visual layer +
          // invisible interaction layer). Camera image planes and other UI
          // meshes must not block empty-space clicks.
          meshObjects.push(obj);
        }
      });

      const pointHits = pointObjects.length > 0
        ? raycaster.intersectObjects(pointObjects, false)
        : [];
      const meshHits = meshObjects.length > 0
        ? raycaster.intersectObjects(meshObjects, false)
        : [];

      if (pointHits.length > 0 || meshHits.length > 0) {
        // Nearest hit decides: a box in front of a point is a box click,
        // which R3F handles separately — only forward point hits here.
        const nearestPoint = pointHits[0]?.distance ?? Infinity;
        const nearestMesh = meshHits[0]?.distance ?? Infinity;
        if (nearestPoint < nearestMesh) {
          const pt = pointHits[0].point;
          onPointClick?.({
            x: parseFloat(pt.x.toFixed(3)),
            y: parseFloat(pt.y.toFixed(3)),
            z: parseFloat(pt.z.toFixed(3)),
          });
        }
        return;
      }

      // Click hit neither a cuboid nor any point cloud — true empty space
      // (sky / no-data area): deselect and restore the full camera panel.
      onEmptyClick?.();
    },
    [scene, camera, gl, onPointClick, onEmptyClick],
  );

  useEffect(() => {
    const canvas = gl.domElement;
    canvas.addEventListener('pointerdown', handlePointerDown);
    canvas.addEventListener('click', handleClick);
    return () => {
      canvas.removeEventListener('pointerdown', handlePointerDown);
      canvas.removeEventListener('click', handleClick);
    };
  }, [gl, handlePointerDown, handleClick]);

  return null;
};
