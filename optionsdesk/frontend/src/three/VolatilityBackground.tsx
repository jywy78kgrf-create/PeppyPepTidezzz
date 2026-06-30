import { useMemo, useRef } from 'react'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import * as THREE from 'three'

/* ===================================================================== */
/*  Volatility-surface background.                                        */
/*                                                                       */
/*  A high-res plane whose vertices are displaced every frame by a sum   */
/*  of travelling sine waves (a stand-in for a slowly morphing implied   */
/*  vol surface). A custom ShaderMaterial shades it with a depth-faded   */
/*  gold/teal gradient and animated contour lines, wrapped in fog and a  */
/*  drifting particle field with parallax for real volumetric depth.     */
/* ===================================================================== */

const surfaceVertex = /* glsl */ `
  uniform float uTime;
  varying float vElevation;
  varying vec2 vUv;
  varying vec3 vWorld;

  // travelling-wave displacement -> morphing surface
  float surf(vec2 p, float t) {
    float e = 0.0;
    e += sin(p.x * 0.55 + t * 0.45) * 0.9;
    e += sin(p.y * 0.42 - t * 0.33) * 0.8;
    e += sin((p.x + p.y) * 0.30 + t * 0.21) * 0.7;
    e += cos((p.x * 0.9 - p.y * 0.7) * 0.5 - t * 0.27) * 0.45;
    // a localized "vol smile" ridge near the money
    float r = length(p * vec2(0.18, 0.10));
    e += exp(-r * r) * 1.6 * (0.7 + 0.3 * sin(t * 0.5));
    return e;
  }

  void main() {
    vUv = uv;
    vec3 pos = position;
    float e = surf(pos.xy, uTime);
    pos.z += e;
    vElevation = e;
    vec4 wp = modelMatrix * vec4(pos, 1.0);
    vWorld = wp.xyz;
    gl_Position = projectionMatrix * viewMatrix * wp;
  }
`

const surfaceFragment = /* glsl */ `
  precision highp float;
  uniform float uTime;
  uniform vec3 uLow;
  uniform vec3 uHigh;
  uniform vec3 uAccent;
  varying float vElevation;
  varying vec2 vUv;
  varying vec3 vWorld;

  void main() {
    float h = clamp(vElevation * 0.32 + 0.5, 0.0, 1.0);
    vec3 base = mix(uLow, uHigh, pow(h, 1.3));

    // animated contour lines along elevation -> "topographic" surface read
    float band = abs(fract(vElevation * 0.9 - uTime * 0.05) - 0.5);
    float contour = smoothstep(0.46, 0.5, band);
    base = mix(base + uAccent * 0.5, base, contour);

    // fine grid in UV for the terminal "data mesh" feel
    vec2 g = abs(fract(vUv * 60.0) - 0.5) / fwidth(vUv * 60.0);
    float grid = 1.0 - min(min(g.x, g.y), 1.0);
    base += uAccent * grid * 0.12;

    // distance fade so the far edge melts into the void
    float dist = length(vWorld.xy);
    float fade = smoothstep(34.0, 8.0, dist);

    // subtle vertical light wash
    float wash = smoothstep(-12.0, 14.0, vWorld.y) * 0.25 + 0.4;

    vec3 col = base * wash;
    float alpha = fade * (0.42 + h * 0.4);
    gl_FragColor = vec4(col, alpha);
  }
`

function Surface() {
  const matRef = useRef<THREE.ShaderMaterial>(null)

  const uniforms = useMemo(
    () => ({
      uTime: { value: 0 },
      uLow: { value: new THREE.Color('#0a1822') },
      uHigh: { value: new THREE.Color('#1d3a4d') },
      uAccent: { value: new THREE.Color('#d8b365') },
    }),
    [],
  )

  useFrame((_, delta) => {
    if (matRef.current) {
      ;(matRef.current.uniforms.uTime.value as number) += delta
    }
  })

  return (
    <mesh rotation={[-Math.PI / 2.32, 0, Math.PI / 5]} position={[0, -3.2, 0]}>
      <planeGeometry args={[60, 60, 220, 220]} />
      <shaderMaterial
        ref={matRef}
        uniforms={uniforms}
        vertexShader={surfaceVertex}
        fragmentShader={surfaceFragment}
        transparent
        wireframe
        depthWrite={false}
        blending={THREE.AdditiveBlending}
      />
    </mesh>
  )
}

// A second, solid copy underneath gives the wireframe a faint volume.
function SurfaceFill() {
  const matRef = useRef<THREE.ShaderMaterial>(null)
  const uniforms = useMemo(
    () => ({
      uTime: { value: 0 },
      uLow: { value: new THREE.Color('#060c12') },
      uHigh: { value: new THREE.Color('#0c2030') },
      uAccent: { value: new THREE.Color('#1a3a44') },
    }),
    [],
  )
  useFrame((_, delta) => {
    if (matRef.current) (matRef.current.uniforms.uTime.value as number) += delta
  })
  return (
    <mesh rotation={[-Math.PI / 2.32, 0, Math.PI / 5]} position={[0, -3.25, 0]}>
      <planeGeometry args={[60, 60, 160, 160]} />
      <shaderMaterial
        ref={matRef}
        uniforms={uniforms}
        vertexShader={surfaceVertex}
        fragmentShader={surfaceFragment}
        transparent
        depthWrite={false}
        opacity={0.5}
      />
    </mesh>
  )
}

// Drifting particle field — dust motes that add parallax depth.
function Particles({ count = 900 }: { count?: number }) {
  const ref = useRef<THREE.Points>(null)
  const { positions, sizes } = useMemo(() => {
    const positions = new Float32Array(count * 3)
    const sizes = new Float32Array(count)
    for (let i = 0; i < count; i++) {
      positions[i * 3 + 0] = (Math.random() - 0.5) * 60
      positions[i * 3 + 1] = (Math.random() - 0.5) * 30
      positions[i * 3 + 2] = (Math.random() - 0.5) * 40 - 6
      sizes[i] = Math.random() * 0.06 + 0.01
    }
    return { positions, sizes }
  }, [count])

  useFrame((state) => {
    if (!ref.current) return
    const t = state.clock.elapsedTime
    ref.current.rotation.y = t * 0.012
    ref.current.position.y = Math.sin(t * 0.1) * 0.6
  })

  return (
    <points ref={ref}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" args={[positions, 3]} />
        <bufferAttribute attach="attributes-size" args={[sizes, 1]} />
      </bufferGeometry>
      <pointsMaterial
        size={0.08}
        sizeAttenuation
        color="#cfe4ec"
        transparent
        opacity={0.5}
        depthWrite={false}
        blending={THREE.AdditiveBlending}
      />
    </points>
  )
}

// Parallax rig: the whole scene drifts subtly with the cursor.
function Rig() {
  const { camera, pointer } = useThree()
  const target = useRef(new THREE.Vector3(0, 0, 0))
  useFrame(() => {
    const px = pointer.x * 2.2
    const py = pointer.y * 1.4
    camera.position.x += (px - camera.position.x) * 0.03
    camera.position.y += (4 + py - camera.position.y) * 0.03
    camera.lookAt(target.current)
  })
  return null
}

export default function VolatilityBackground() {
  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 0,
        background:
          'radial-gradient(130% 100% at 50% -10%, #0a1018 0%, #06080d 45%, #04060a 100%)',
      }}
    >
      <Canvas
        dpr={[1, 1.75]}
        gl={{ antialias: true, alpha: true, powerPreference: 'high-performance' }}
        camera={{ position: [0, 4, 18], fov: 48, near: 0.1, far: 120 }}
      >
        <fog attach="fog" args={['#05080d', 16, 52]} />
        <ambientLight intensity={0.4} />
        <SurfaceFill />
        <Surface />
        <Particles />
        <Rig />
      </Canvas>
    </div>
  )
}
