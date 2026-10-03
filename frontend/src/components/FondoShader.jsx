import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';

/**
 * Fondo animado por shader: la onda cromática, en colores de CGR.
 *
 * Es el componente `WebGLShader` de la plantilla, portado al stack real de
 * este proyecto —React con Vite y JavaScript, no Next.js con TypeScript—. Se
 * quitó el `"use client"`, que es una directiva del App Router de Next y aquí
 * no significa nada, y las clases de Tailwind se sustituyeron por CSS propio.
 *
 * La estructura del shader se conservó: tres ondas con la componente `x`
 * desplazada entre sí, que es lo que produce el borde franjeado. Lo que
 * cambió es que ya no alimentan los canales rojo, verde y azul —eso daba un
 * arcoíris que no tenía nada que ver con la marca— sino tres colores de CGR
 * que se suman como luz.
 */
export default function FondoShader({
  escalaX = 1.0,
  escalaY = 0.5,
  distorsion = 0.05,
  velocidad = 0.01,
  // **La cresta de la onda hay que domarla.** El shader calcula el color como
  // `intensidad / abs(...)`, y eso no tiene techo: en el centro de la onda la
  // división tiende a infinito y satura a blanco puro. Con el valor original
  // —0.05— la cresta pasaba por detrás del panel y borraba el texto de ayuda,
  // que es gris. Bajarlo estrecha el núcleo brillante sin apagar la onda.
  //
  // Sube un poco respecto al valor con el que se calibró en blanco: los tres
  // colores de marca son más oscuros que el blanco puro, así que a igual
  // divisor la onda salía más apagada.
  intensidad = 0.034,
}) {
  const lienzo = useRef(null);
  const [soportado, setSoportado] = useState(true);

  useEffect(() => {
    const canvas = lienzo.current;
    if (!canvas) return undefined;

    const vertexShader = `
      attribute vec3 position;
      void main() {
        gl_Position = vec4(position, 1.0);
      }
    `;

    const fragmentShader = `
      precision highp float;
      uniform vec2 resolution;
      uniform float time;
      uniform float xScale;
      uniform float yScale;
      uniform float distortion;
      uniform float intensity;
      uniform vec3 colorExterno;
      uniform vec3 colorMedio;
      uniform vec3 colorInterno;

      void main() {
        vec2 p = (gl_FragCoord.xy * 2.0 - resolution) / min(resolution.x, resolution.y);

        float d = length(p) * distortion;

        float rx = p.x * (1.0 + d);
        float gx = p.x;
        float bx = p.x * (1.0 - d);

        // Los tres lóbulos siguen desplazados entre sí —de ahí el borde
        // franjeado, que es lo bonito del efecto— pero ya no alimentan los
        // canales rojo, verde y azul: cada uno lleva un color de la marca y se
        // suman. En los bordes se ve cada color por separado; donde los tres
        // se solapan la suma satura y el núcleo sale blanco, que es
        // exactamente como se comporta la luz.
        float lo = intensity / abs(p.y + sin((rx + time) * xScale) * yScale);
        float lm = intensity / abs(p.y + sin((gx + time) * xScale) * yScale);
        float li = intensity / abs(p.y + sin((bx + time) * xScale) * yScale);

        vec3 color = lo * colorExterno + lm * colorMedio + li * colorInterno;

        gl_FragColor = vec4(color, 1.0);
      }
    `;

    let renderer;
    try {
      renderer = new THREE.WebGLRenderer({ canvas, antialias: false });
    } catch (err) {
      // **Si no hay WebGL, no hay drama.** Una terminal vieja, un driver en
      // lista negra o una máquina virtual pueden no darlo. En ese caso el
      // componente no pinta nada y queda el fondo de CSS, que ya existe. Sin
      // esto, el login entero se caería por un adorno.
      setSoportado(false);
      return undefined;
    }

    // **Se limita la densidad de píxeles.** El original usaba
    // `window.devicePixelRatio` a pelo: en una pantalla al 200 % eso son
    // cuatro veces los píxeles a calcular en cada fotograma. Para un degradado
    // suave la diferencia no se ve, y en una terminal de planta con gráficos
    // integrados es la diferencia entre ir fluido y no.
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
    renderer.setClearColor(new THREE.Color(0x000000));

    const scene = new THREE.Scene();
    const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, -1);

    const uniforms = {
      resolution: { value: [window.innerWidth, window.innerHeight] },
      time: { value: 0.0 },
      xScale: { value: escalaX },
      yScale: { value: escalaY },
      distortion: { value: distorsion },
      intensity: { value: intensidad },
      // La paleta de CGR, en el orden en que se abre el franjeado:
      //   Fancy pink  #b31671  primario
      //   Cool blue   #148ec2  secundario, hace de puente
      //   Solid blue  #1b3d79  primario
      // El azul sólido es el más oscuro de los tres y por eso va en el lóbulo
      // interior: en una suma de luces, el color oscuro aporta poco, y ahí es
      // donde menos se necesita que aporte.
      colorExterno: { value: [0.702, 0.086, 0.443] },
      colorMedio: { value: [0.078, 0.557, 0.761] },
      colorInterno: { value: [0.106, 0.239, 0.475] },
    };

    // Un rectángulo que cubre la pantalla en coordenadas de recorte. El
    // vértice escribe `gl_Position` directamente, así que la cámara no
    // interviene: está por lo que pide la API, no porque haga nada.
    const posiciones = new Float32Array([
      -1, -1, 0, 1, -1, 0, -1, 1, 0,
      1, -1, 0, -1, 1, 0, 1, 1, 0,
    ]);
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(posiciones, 3));

    const material = new THREE.RawShaderMaterial({
      vertexShader,
      fragmentShader,
      uniforms,
      side: THREE.DoubleSide,
    });

    const mesh = new THREE.Mesh(geometry, material);
    scene.add(mesh);

    const redimensionar = () => {
      const ancho = window.innerWidth;
      const alto = window.innerHeight;
      // `false` para no tocar el `style`: el tamaño en pantalla lo pone el CSS.
      renderer.setSize(ancho, alto, false);
      uniforms.resolution.value = [ancho, alto];
    };
    redimensionar();

    // **Se respeta «reducir movimiento».** Pero no apagando el fondo: se pinta
    // un fotograma y se deja quieto. Quien pide menos movimiento no pide una
    // pantalla negra.
    const quieto = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    let cuadro = null;
    const animar = () => {
      uniforms.time.value += velocidad;
      renderer.render(scene, camera);
      cuadro = requestAnimationFrame(animar);
    };

    if (quieto) {
      renderer.render(scene, camera);
    } else {
      animar();
    }

    // **Se atiende la pérdida de contexto.** El navegador puede quitarle el
    // contexto WebGL a una pestaña —cambio de GPU, suspensión, presión de
    // memoria— y entonces el lienzo se queda en negro para siempre. Al
    // perderlo se retira el componente y vuelve a verse el fondo de CSS.
    const alPerderContexto = (e) => {
      e.preventDefault();
      if (cuadro) cancelAnimationFrame(cuadro);
      setSoportado(false);
    };
    canvas.addEventListener('webglcontextlost', alPerderContexto);
    window.addEventListener('resize', redimensionar);

    return () => {
      if (cuadro) cancelAnimationFrame(cuadro);
      window.removeEventListener('resize', redimensionar);
      canvas.removeEventListener('webglcontextlost', alPerderContexto);
      scene.remove(mesh);
      geometry.dispose();
      material.dispose();
      renderer.dispose();
    };
  }, [escalaX, escalaY, distorsion, velocidad, intensidad]);

  if (!soportado) return null;

  return <canvas ref={lienzo} className="fondo-shader" aria-hidden="true" />;
}
