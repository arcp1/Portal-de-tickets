import { useEffect, useRef, useState } from 'react';

/**
 * Fondo de alambre geométrico en WebGL, con el resorte de CGR como figura.
 *
 * **AHORA MISMO NO ESTÁ MONTADO.** El fondo en uso es `FondoShader`, la onda
 * cromática. Éste se conserva porque funciona y porque el fondo del login ha
 * cambiado varias veces; para volver a él, en `App.jsx` se cambia el `import`
 * diferido y el JSX. Mientras nadie lo importe no entra en el paquete, así
 * que tenerlo aquí no cuesta ni un byte al usuario.
 *
 * Es el componente `GeometricBlurMesh` de la plantilla, portado al stack real
 * de este proyecto —React con Vite y JavaScript, no Next con TypeScript— y
 * adaptado para vivir *detrás* de un formulario en vez de ser la página
 * entera. Se quitó el `"use client"`, que es una directiva del App Router de
 * Next y aquí no significa nada, y las clases de Tailwind pasaron a CSS.
 *
 * **No usa three.js.** Es WebGL a pelo, así que al montarlo se pudo quitar esa
 * dependencia del proyecto: 128 KB comprimidos menos en la primera carga.
 *
 * La figura por defecto es el resorte; el resto de los poliedros del original
 * siguen ahí y se pueden pedir por prop.
 */

/** Las figuras, en el orden en que las entiende el shader. */
export const FIGURAS = [
  'Cubo', 'Tetraedro', 'Octaedro', 'Icosaedro',
  'Pirámide', 'Diamante', 'Prisma hexagonal', 'Resorte', 'Transformación',
];

export const RESORTE = 7;

const vertexShader = `
attribute vec3 a_position;
attribute vec2 a_uv;
varying vec2 v_texcoord;

void main() {
    gl_Position = vec4(a_position, 1.0);
    v_texcoord = a_uv;
}
`;

const fragmentShader = `
#ifdef GL_ES
precision highp float;
#endif

uniform vec2 u_mouse;
uniform vec2 u_resolution;
uniform float u_pixelRatio;
uniform float u_time;
uniform int u_shape;
uniform vec3 u_colorA;
uniform vec3 u_colorB;
uniform vec2 u_offset;

#define PI 3.1415926535897932384626433832795
#define TWO_PI 6.2831853071795864769252867665590

// Cuántos tramos rectos forman la hélice del resorte. Es una constante y no
// un uniform porque GLSL ES 1.00 exige que los bucles tengan límite conocido
// al compilar. Y es 56 y no 100 a propósito: **cada tramo se evalúa una vez
// por píxel**. A pantalla completa son unos 48 millones de distancias
// punto-segmento por fotograma; el doble de tramos es el doble de eso, y en
// una terminal de planta con gráficos integrados eso se nota. A 56 la curva
// ya se lee redonda.
// **Dos cosas hay que acertar a la vez, y son independientes.**
//
//   Tramos POR VUELTA: la primera versión tenía 8, y un círculo de 8 lados es
//   un octágono; el resorte salía como un zigzag. Hacen falta 16 para que la
//   espira se lea redonda.
//
//   VUELTAS, y lo juntas que están: con 4 espiras repartidas en todo el largo,
//   el paso era mayor que el radio y la pieza parecía alambre doblado, no un
//   resorte. Un muelle de extensión real lleva las espiras tocándose.
//
// 144 tramos en 9 vueltas cumple las dos. Y el número importa: **cada tramo se
// evalúa una vez por píxel**, así que a pantalla completa son unos 110
// millones de distancias punto-segmento por fotograma. Es el techo de lo que
// se puede pedir aquí.
const int PASOS_HELICE = 144;
const int PASOS_GANCHO = 10;

mat3 rotateX(float a) {
    float s = sin(a); float c = cos(a);
    return mat3(1.0, 0.0, 0.0, 0.0, c, -s, 0.0, s, c);
}
mat3 rotateY(float a) {
    float s = sin(a); float c = cos(a);
    return mat3(c, 0.0, s, 0.0, 1.0, 0.0, -s, 0.0, c);
}
mat3 rotateZ(float a) {
    float s = sin(a); float c = cos(a);
    return mat3(c, -s, 0.0, s, c, 0.0, 0.0, 0.0, 1.0);
}

vec2 coord(in vec2 p) {
    p = p / u_resolution.xy;
    if (u_resolution.x > u_resolution.y) {
        p.x *= u_resolution.x / u_resolution.y;
        p.x += (u_resolution.y - u_resolution.x) / u_resolution.y / 2.0;
    } else {
        p.y *= u_resolution.y / u_resolution.x;
        p.y += (u_resolution.x - u_resolution.y) / u_resolution.x / 2.0;
    }
    p -= 0.5;
    return p;
}

vec2 project(vec3 p) {
    float perspective = 2.0 / (2.0 - p.z);
    // El desplazamiento saca la figura del centro. Sin él, la pieza queda
    // justo detrás de la tarjeta del formulario y solo asoman los ganchos:
    // se ve un par de arcos sueltos y no se entiende qué es.
    return p.xy * perspective + u_offset;
}

float distToSegment(vec2 p, vec2 a, vec2 b) {
    vec2 pa = p - a;
    vec2 ba = b - a;
    float h = clamp(dot(pa, ba) / dot(ba, ba), 0.0, 1.0);
    return length(pa - ba * h);
}

float drawLine(vec2 p, vec2 a, vec2 b, float thickness, float blur) {
    float d = distToSegment(p, a, b);
    return smoothstep(thickness + blur, thickness - blur, d);
}

void getCubeVertices(out vec3 v[8]) {
    float s = 0.7;
    v[0] = vec3(-s, -s, -s); v[1] = vec3( s, -s, -s);
    v[2] = vec3( s,  s, -s); v[3] = vec3(-s,  s, -s);
    v[4] = vec3(-s, -s,  s); v[5] = vec3( s, -s,  s);
    v[6] = vec3( s,  s,  s); v[7] = vec3(-s,  s,  s);
}

void getOctahedronVertices(out vec3 v[6]) {
    v[0] = vec3( 1.0, 0.0, 0.0); v[1] = vec3(-1.0, 0.0, 0.0);
    v[2] = vec3( 0.0, 1.0, 0.0); v[3] = vec3( 0.0,-1.0, 0.0);
    v[4] = vec3( 0.0, 0.0, 1.0); v[5] = vec3( 0.0, 0.0,-1.0);
}

/**
 * El resorte de extensión.
 *
 * El cuerpo no son vértices escritos a mano como en los poliedros: es la
 * ecuación paramétrica de una hélice recorrida en un bucle, uniendo cada
 * punto con el anterior. Así el número de espiras y el paso son números que
 * se cambian en una línea, en vez de una lista de aristas.
 *
 * Los ganchos son arcos en el plano que contiene el eje, uno arriba y otro
 * abajo. No cierran del todo —van hasta 1.7 PI y no hasta 2 PI— porque un
 * gancho de tensión real queda abierto: por ese hueco es por donde entra lo
 * que se va a tensar.
 */
float dibujarResorte(vec2 p, mat3 rotation, float scale, float thickness, float blur) {
    float result = 0.0;

    float radio   = 0.55;
    float alto    = 0.78;   // media longitud del cuerpo
    float vueltas = 9.0;

    // ---- Cuerpo: la hélice ----
    vec3 anterior = vec3(0.0);
    for (int i = 0; i <= PASOS_HELICE; i++) {
        float u = float(i) / float(PASOS_HELICE);
        float t = u * vueltas * TWO_PI;
        vec3 punto = vec3(radio * cos(t),
                          mix(-alto, alto, u),
                          radio * sin(t));
        punto = rotation * (punto * scale);
        if (i > 0) {
            result += drawLine(p, project(anterior), project(punto), thickness, blur);
        }
        anterior = punto;
    }

    // ---- Ganchos ----
    // El gancho, más corto que en el primer intento: con 0.78 del radio, los
    // dos arcos añadían casi tanto largo como el cuerpo y la pieza se salía de
    // la pantalla por arriba y por abajo.
    float rg = radio * 0.55;

    // Superior: el arco nace donde termina el cuerpo y sube.
    vec3 prevSup = vec3(0.0);
    for (int i = 0; i <= PASOS_GANCHO; i++) {
        float a = (float(i) / float(PASOS_GANCHO)) * 1.7 * PI;
        vec3 punto = vec3(rg * sin(a), alto + rg - rg * cos(a), 0.0);
        punto = rotation * (punto * scale);
        if (i > 0) {
            result += drawLine(p, project(prevSup), project(punto), thickness, blur);
        }
        prevSup = punto;
    }

    // Inferior: el mismo arco reflejado.
    vec3 prevInf = vec3(0.0);
    for (int i = 0; i <= PASOS_GANCHO; i++) {
        float a = (float(i) / float(PASOS_GANCHO)) * 1.7 * PI;
        vec3 punto = vec3(rg * sin(a), -alto - rg + rg * cos(a), 0.0);
        punto = rotation * (punto * scale);
        if (i > 0) {
            result += drawLine(p, project(prevInf), project(punto), thickness, blur);
        }
        prevInf = punto;
    }

    return result;
}

float drawWireframe(vec2 p, int shape, mat3 rotation, float scale, float thickness, float blur) {
    float result = 0.0;

    if (shape == 0) {
        vec3 v[8];
        getCubeVertices(v);
        for (int i = 0; i < 8; i++) { v[i] = rotation * (v[i] * scale); }
        result += drawLine(p, project(v[0]), project(v[1]), thickness, blur);
        result += drawLine(p, project(v[1]), project(v[2]), thickness, blur);
        result += drawLine(p, project(v[2]), project(v[3]), thickness, blur);
        result += drawLine(p, project(v[3]), project(v[0]), thickness, blur);
        result += drawLine(p, project(v[4]), project(v[5]), thickness, blur);
        result += drawLine(p, project(v[5]), project(v[6]), thickness, blur);
        result += drawLine(p, project(v[6]), project(v[7]), thickness, blur);
        result += drawLine(p, project(v[7]), project(v[4]), thickness, blur);
        result += drawLine(p, project(v[0]), project(v[4]), thickness, blur);
        result += drawLine(p, project(v[1]), project(v[5]), thickness, blur);
        result += drawLine(p, project(v[2]), project(v[6]), thickness, blur);
        result += drawLine(p, project(v[3]), project(v[7]), thickness, blur);

    } else if (shape == 1) {
        float a = 1.0 / sqrt(3.0);
        vec3 v[4];
        v[0] = vec3( a,  a,  a); v[1] = vec3( a, -a, -a);
        v[2] = vec3(-a,  a, -a); v[3] = vec3(-a, -a,  a);
        for (int i = 0; i < 4; i++) { v[i] = rotation * (v[i] * scale); }
        result += drawLine(p, project(v[0]), project(v[1]), thickness, blur);
        result += drawLine(p, project(v[0]), project(v[2]), thickness, blur);
        result += drawLine(p, project(v[0]), project(v[3]), thickness, blur);
        result += drawLine(p, project(v[1]), project(v[2]), thickness, blur);
        result += drawLine(p, project(v[1]), project(v[3]), thickness, blur);
        result += drawLine(p, project(v[2]), project(v[3]), thickness, blur);

    } else if (shape == 2) {
        vec3 v[6];
        getOctahedronVertices(v);
        for (int i = 0; i < 6; i++) { v[i] = rotation * (v[i] * scale); }
        result += drawLine(p, project(v[2]), project(v[0]), thickness, blur);
        result += drawLine(p, project(v[2]), project(v[1]), thickness, blur);
        result += drawLine(p, project(v[2]), project(v[4]), thickness, blur);
        result += drawLine(p, project(v[2]), project(v[5]), thickness, blur);
        result += drawLine(p, project(v[3]), project(v[0]), thickness, blur);
        result += drawLine(p, project(v[3]), project(v[1]), thickness, blur);
        result += drawLine(p, project(v[3]), project(v[4]), thickness, blur);
        result += drawLine(p, project(v[3]), project(v[5]), thickness, blur);
        result += drawLine(p, project(v[0]), project(v[4]), thickness, blur);
        result += drawLine(p, project(v[4]), project(v[1]), thickness, blur);
        result += drawLine(p, project(v[1]), project(v[5]), thickness, blur);
        result += drawLine(p, project(v[5]), project(v[0]), thickness, blur);

    } else if (shape == 4) {
        vec3 v[5];
        float s = 0.7;
        v[0] = vec3(-s, 0.0, -s); v[1] = vec3( s, 0.0, -s);
        v[2] = vec3( s, 0.0,  s); v[3] = vec3(-s, 0.0,  s);
        v[4] = vec3( 0.0, 1.0, 0.0);
        for (int i = 0; i < 5; i++) { v[i] = rotation * (v[i] * scale); }
        result += drawLine(p, project(v[0]), project(v[1]), thickness, blur);
        result += drawLine(p, project(v[1]), project(v[2]), thickness, blur);
        result += drawLine(p, project(v[2]), project(v[3]), thickness, blur);
        result += drawLine(p, project(v[3]), project(v[0]), thickness, blur);
        result += drawLine(p, project(v[0]), project(v[4]), thickness, blur);
        result += drawLine(p, project(v[1]), project(v[4]), thickness, blur);
        result += drawLine(p, project(v[2]), project(v[4]), thickness, blur);
        result += drawLine(p, project(v[3]), project(v[4]), thickness, blur);

    } else if (shape == 5) {
        vec3 v[6];
        float s = 0.6;
        v[0] = vec3(-s, 0.0, -s); v[1] = vec3( s, 0.0, -s);
        v[2] = vec3( s, 0.0,  s); v[3] = vec3(-s, 0.0,  s);
        v[4] = vec3( 0.0,  1.0, 0.0); v[5] = vec3( 0.0, -1.0, 0.0);
        for (int i = 0; i < 6; i++) { v[i] = rotation * (v[i] * scale); }
        result += drawLine(p, project(v[0]), project(v[1]), thickness, blur);
        result += drawLine(p, project(v[1]), project(v[2]), thickness, blur);
        result += drawLine(p, project(v[2]), project(v[3]), thickness, blur);
        result += drawLine(p, project(v[3]), project(v[0]), thickness, blur);
        result += drawLine(p, project(v[0]), project(v[4]), thickness, blur);
        result += drawLine(p, project(v[1]), project(v[4]), thickness, blur);
        result += drawLine(p, project(v[2]), project(v[4]), thickness, blur);
        result += drawLine(p, project(v[3]), project(v[4]), thickness, blur);
        result += drawLine(p, project(v[0]), project(v[5]), thickness, blur);
        result += drawLine(p, project(v[1]), project(v[5]), thickness, blur);
        result += drawLine(p, project(v[2]), project(v[5]), thickness, blur);
        result += drawLine(p, project(v[3]), project(v[5]), thickness, blur);

    } else if (shape == 7) {
        result += dibujarResorte(p, rotation, scale, thickness, blur);

    } else {
        // Transformación: cubo que se abre hacia octaedro.
        float t = u_time * 0.5;
        float morph = sin(t) * 0.5 + 0.5;
        vec3 cubo[8]; getCubeVertices(cubo);
        vec3 octa[6]; getOctahedronVertices(octa);
        vec3 v[8];
        for (int i = 0; i < 8; i++) {
            if (i < 6) { v[i] = mix(cubo[i], octa[i] * 1.5, morph); }
            else { v[i] = cubo[i] * (1.0 - morph * 0.3); }
            v[i] = rotation * (v[i] * scale);
        }
        float alpha = 1.0 - morph * 0.5;
        result += drawLine(p, project(v[0]), project(v[1]), thickness, blur) * alpha;
        result += drawLine(p, project(v[1]), project(v[2]), thickness, blur) * alpha;
        result += drawLine(p, project(v[2]), project(v[3]), thickness, blur) * alpha;
        result += drawLine(p, project(v[3]), project(v[0]), thickness, blur) * alpha;
        result += drawLine(p, project(v[4]), project(v[5]), thickness, blur) * alpha;
        result += drawLine(p, project(v[5]), project(v[6]), thickness, blur) * alpha;
        result += drawLine(p, project(v[6]), project(v[7]), thickness, blur) * alpha;
        result += drawLine(p, project(v[7]), project(v[4]), thickness, blur) * alpha;
        result += drawLine(p, project(v[0]), project(v[6]), thickness, blur) * morph;
        result += drawLine(p, project(v[1]), project(v[7]), thickness, blur) * morph;
        result += drawLine(p, project(v[2]), project(v[4]), thickness, blur) * morph;
        result += drawLine(p, project(v[3]), project(v[5]), thickness, blur) * morph;
    }

    return clamp(result, 0.0, 1.0);
}

vec3 render(vec2 st, vec2 mouse) {
    float mouseDistance = length(st - mouse);
    float mouseInfluence = 1.0 - smoothstep(0.0, 0.5, mouseDistance);

    float time = u_time * 0.2;
    mat3 rotation = rotateY(time + (mouse.x - 0.5) * mouseInfluence * 1.0) *
                    rotateX(time * 0.7 + (mouse.y - 0.5) * mouseInfluence * 1.0) *
                    rotateZ(time * 0.1);

    float scale = 0.48;

    // Cerca del ratón se desenfoca; lejos, el trazo es nítido.
    float blur = mix(0.0001, 0.05, mouseInfluence);
    float thickness = mix(0.0022, 0.0032, mouseInfluence);

    float shape = drawWireframe(st, u_shape, rotation, scale, thickness, blur);

    // El alambre va del azul al rosa de CGR según la altura, en vez del
    // blanco del original: es el mismo par de primarios del logotipo y del
    // degradado de los títulos.
    vec3 color = mix(u_colorA, u_colorB, clamp(st.y * 1.4 + 0.5, 0.0, 1.0));

    float dimming = 1.0 - mouseInfluence * 0.3;
    color *= shape * dimming;

    float vignette = 1.0 - length(st) * 0.2;
    color *= vignette;

    return pow(color, vec3(0.9));
}

void main() {
    vec2 st = coord(gl_FragCoord.xy);
    vec2 mouse = coord(u_mouse * u_pixelRatio) * vec2(1., -1.);
    gl_FragColor = vec4(render(st, mouse), 1.0);
}
`;

export default function MallaGeometrica({
  figura = RESORTE,
  // El original cambiaba de figura al hacer clic en cualquier sitio y con las
  // teclas 1-8. **Aquí eso está apagado por defecto y no es un descuido:**
  // este fondo vive debajo de un formulario donde se teclea un número de
  // empleado, y un oyente global de teclado convertiría cada "3" del número
  // en un cambio de figura. La interacción se puede pedir, pero no en la
  // pantalla donde la gente escribe.
  interactivo = false,
  colorA = [0.294, 0.690, 0.902],   // #4bb0e6, de Cool blue
  colorB = [0.890, 0.373, 0.675],   // #e35fac, de Fancy pink
  // Hacia la derecha: la tarjeta del login está centrada, y una figura
  // centrada queda escondida detrás de ella.
  desplazamiento = [0.16, 0.02],
}) {
  const lienzo = useRef(null);
  const raton = useRef({ x: 0, y: 0 });
  const ratonSuave = useRef({ x: 0, y: 0 });
  const [soportado, setSoportado] = useState(true);
  const [figuraActual, setFiguraActual] = useState(figura);

  useEffect(() => { setFiguraActual(figura); }, [figura]);

  useEffect(() => {
    const canvas = lienzo.current;
    if (!canvas) return undefined;

    const gl = canvas.getContext('webgl', {
      antialias: true, alpha: false, premultipliedAlpha: false,
      preserveDrawingBuffer: false, powerPreference: 'low-power',
    });
    if (!gl) { setSoportado(false); return undefined; }

    const compilar = (tipo, fuente) => {
      const sh = gl.createShader(tipo);
      gl.shaderSource(sh, fuente);
      gl.compileShader(sh);
      if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
        console.error('Shader:', gl.getShaderInfoLog(sh));
        gl.deleteShader(sh);
        return null;
      }
      return sh;
    };

    const vs = compilar(gl.VERTEX_SHADER, vertexShader);
    const fs = compilar(gl.FRAGMENT_SHADER, fragmentShader);
    if (!vs || !fs) { setSoportado(false); return undefined; }

    const program = gl.createProgram();
    gl.attachShader(program, vs);
    gl.attachShader(program, fs);
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      console.error('Programa:', gl.getProgramInfoLog(program));
      setSoportado(false);
      return undefined;
    }
    gl.useProgram(program);

    const u = {
      mouse: gl.getUniformLocation(program, 'u_mouse'),
      resolution: gl.getUniformLocation(program, 'u_resolution'),
      pixelRatio: gl.getUniformLocation(program, 'u_pixelRatio'),
      time: gl.getUniformLocation(program, 'u_time'),
      shape: gl.getUniformLocation(program, 'u_shape'),
      colorA: gl.getUniformLocation(program, 'u_colorA'),
      colorB: gl.getUniformLocation(program, 'u_colorB'),
      offset: gl.getUniformLocation(program, 'u_offset'),
    };

    const bufPos = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, bufPos);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([
      -1, -1, 0, 1, -1, 0, -1, 1, 0, 1, 1, 0,
    ]), gl.STATIC_DRAW);
    const locPos = gl.getAttribLocation(program, 'a_position');
    gl.enableVertexAttribArray(locPos);
    gl.vertexAttribPointer(locPos, 3, gl.FLOAT, false, 0, 0);

    const bufUv = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, bufUv);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([0, 0, 1, 0, 0, 1, 1, 1]), gl.STATIC_DRAW);
    const locUv = gl.getAttribLocation(program, 'a_uv');
    gl.enableVertexAttribArray(locUv);
    gl.vertexAttribPointer(locUv, 2, gl.FLOAT, false, 0, 0);

    // **La densidad de píxeles se limita a 1.25.** Cada tramo del resorte se
    // evalúa una vez por píxel; a `devicePixelRatio` completo en una pantalla
    // al 200 % son cuatro veces ese trabajo, para un alambre que además está
    // detrás de un cristal desenfocado.
    const dpr = Math.min(window.devicePixelRatio || 1, 1.25);

    const redimensionar = () => {
      const ancho = window.innerWidth;
      const alto = window.innerHeight;
      canvas.width = Math.floor(ancho * dpr);
      canvas.height = Math.floor(alto * dpr);
      gl.viewport(0, 0, canvas.width, canvas.height);
    };
    redimensionar();

    const alMover = (e) => {
      const t = e.touches ? e.touches[0] : e;
      raton.current = { x: t.clientX, y: t.clientY };
    };

    const quieto = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const inicio = Date.now();
    let cuadro = null;
    let ultimo = performance.now();

    const pintar = (ahora) => {
      const delta = Math.min((ahora - ultimo) / 1000, 0.1);
      ultimo = ahora;

      const amortiguacion = 8;
      ratonSuave.current.x += (raton.current.x - ratonSuave.current.x) * amortiguacion * delta;
      ratonSuave.current.y += (raton.current.y - ratonSuave.current.y) * amortiguacion * delta;

      gl.clearColor(0.027, 0.043, 0.082, 1.0);   // el `--bg-primary` del portal
      gl.clear(gl.COLOR_BUFFER_BIT);

      gl.uniform2f(u.mouse, ratonSuave.current.x, ratonSuave.current.y);
      gl.uniform2f(u.resolution, canvas.width, canvas.height);
      gl.uniform1f(u.pixelRatio, dpr);
      gl.uniform1f(u.time, quieto ? 12.0 : (Date.now() - inicio) / 1000);
      gl.uniform1i(u.shape, figuraActual);
      gl.uniform3f(u.colorA, colorA[0], colorA[1], colorA[2]);
      gl.uniform3f(u.colorB, colorB[0], colorB[1], colorB[2]);
      gl.uniform2f(u.offset, desplazamiento[0], desplazamiento[1]);

      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);

      // Con «reducir movimiento» se pinta un fotograma y se para. Quien pide
      // menos movimiento no pide una pantalla negra.
      if (!quieto) cuadro = requestAnimationFrame(pintar);
    };
    cuadro = requestAnimationFrame(pintar);

    const alPerderContexto = (e) => {
      e.preventDefault();
      if (cuadro) cancelAnimationFrame(cuadro);
      setSoportado(false);
    };

    window.addEventListener('resize', redimensionar);
    window.addEventListener('mousemove', alMover);
    window.addEventListener('touchmove', alMover);
    canvas.addEventListener('webglcontextlost', alPerderContexto);

    let alPulsarTecla;
    if (interactivo) {
      alPulsarTecla = (e) => {
        const n = parseInt(e.key, 10);
        if (n >= 1 && n <= FIGURAS.length) setFiguraActual(n - 1);
      };
      window.addEventListener('keypress', alPulsarTecla);
    }

    return () => {
      if (cuadro) cancelAnimationFrame(cuadro);
      window.removeEventListener('resize', redimensionar);
      window.removeEventListener('mousemove', alMover);
      window.removeEventListener('touchmove', alMover);
      canvas.removeEventListener('webglcontextlost', alPerderContexto);
      if (alPulsarTecla) window.removeEventListener('keypress', alPulsarTecla);
      gl.deleteProgram(program);
      gl.deleteShader(vs);
      gl.deleteShader(fs);
      gl.deleteBuffer(bufPos);
      gl.deleteBuffer(bufUv);
    };
  }, [figuraActual, interactivo, colorA, colorB, desplazamiento]);

  if (!soportado) return null;

  return <canvas ref={lienzo} className="fondo-shader" aria-hidden="true" />;
}
