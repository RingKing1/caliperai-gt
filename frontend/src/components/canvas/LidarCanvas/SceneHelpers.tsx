import React, { useRef, useEffect, useMemo } from 'react';
import * as THREE from 'three';

export const GroundGrid: React.FC = () => {
  const ref = useRef<THREE.GridHelper>(null);

  useEffect(() => {
    if (ref.current) {
      ref.current.raycast = () => {};
    }
  }, []);

  return (
    <gridHelper
      ref={ref}
      args={[200, 200, '#334155', '#1e293b']}
      rotation={[Math.PI / 2, 0, 0]}
      position={[0, 0, -2]}
    />
  );
};

export const AxesIndicator: React.FC = () => {
  const ref = useRef<THREE.AxesHelper>(null);

  useEffect(() => {
    if (ref.current) {
      ref.current.raycast = () => {};
    }
  }, []);

  return (
    <group position={[-45, -45, 0]}>
      <axesHelper ref={ref} args={[5]} />
    </group>
  );
};

/**
 * Concentric distance rings centred on the ego vehicle.
 *
 * LiDAR frame: +X forward, +Y left, +Z up, ego at origin. The rings therefore
 * live in the XY plane; they sit just above the ground grid so the two do not
 * z-fight. `raycast` is disabled so ring lines never swallow box clicks.
 */
const ringMaterial = (opacity: number) =>
  new THREE.LineBasicMaterial({
    color: '#3f6f8f',
    transparent: true,
    opacity,
    depthWrite: false,
  });

export const DistanceRings: React.FC<{
  radii?: number[];
  z?: number;
  /** Draw a distance label at the +X edge of every ring. */
  showLabels?: boolean;
}> = ({ radii = [30, 60], z = -1.85, showLabels = true }) => {
  const groupRef = useRef<THREE.Group>(null);

  const circles = useMemo(() => {
    const SEGMENTS = 160;
    return radii.map((radius) => {
      const points: THREE.Vector3[] = [];
      for (let i = 0; i <= SEGMENTS; i += 1) {
        const a = (i / SEGMENTS) * Math.PI * 2;
        points.push(new THREE.Vector3(Math.cos(a) * radius, Math.sin(a) * radius, 0));
      }
      const geometry = new THREE.BufferGeometry().setFromPoints(points);
      // Outer ring slightly brighter than intermediate ones.
      const isOuter = radius === Math.max(...radii);
      return { radius, geometry, material: ringMaterial(isOuter ? 0.42 : 0.3) };
    });
  }, [radii]);

  // Labels are rendered as canvas-texture sprites so we don't need a font loader.
  const labels = useMemo(() => {
    if (!showLabels) return [];
    return radii.map((radius) => {
      const canvas = document.createElement('canvas');
      canvas.width = 128;
      canvas.height = 64;
      const ctx = canvas.getContext('2d');
      if (ctx) {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.font = 'bold 52px sans-serif';
        ctx.fillStyle = '#b8dcf0';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(`${radius}m`, canvas.width / 2, canvas.height / 2);
      }
      const texture = new THREE.CanvasTexture(canvas);
      texture.needsUpdate = true;
      const material = new THREE.SpriteMaterial({
        map: texture,
        transparent: true,
        depthWrite: false,
        opacity: 0.95,
      });
      const sprite = new THREE.Sprite(material);
      // Place at 45° so the label never sits on the +X heading axis.
      const d = radius * Math.SQRT1_2;
      sprite.position.set(d, d, 0.8);
      sprite.scale.set(9, 4.5, 1);
      sprite.raycast = () => {};
      return { radius, sprite, texture, material };
    });
  }, [radii, showLabels]);

  useEffect(() => {
    const group = groupRef.current;
    if (group) group.raycast = () => {};
  }, []);

  // Dispose GPU resources on unmount / radius change.
  useEffect(() => () => {
    circles.forEach(({ geometry, material }) => {
      geometry.dispose();
      material.dispose();
    });
    labels.forEach(({ texture, material }) => {
      texture.dispose();
      material.dispose();
    });
  }, [circles, labels]);

  return (
    <group ref={groupRef} position={[0, 0, z]}>
      {circles.map(({ radius, geometry, material }) => (
        <lineLoop key={`ring-${radius}`} geometry={geometry} material={material} />
      ))}
      {labels.map(({ radius, sprite }) => (
        <primitive key={`ring-label-${radius}`} object={sprite} />
      ))}
    </group>
  );
};
