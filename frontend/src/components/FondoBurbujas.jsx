import { useEffect, useMemo, useRef } from 'react';

/**
 * Fondo de esferas líquidas: el efecto "gooey" del componente Mercury.
 *
 * Seis esferas flotando con una animación de CSS, todas dentro de un
 * contenedor con un filtro SVG que las funde cuando se acercan. La receta es
 * la clásica: **desenfocar y luego subir el contraste del canal alfa**. El
 * desenfoque hace que los bordes de dos esferas próximas se solapen en una
 * zona de alfa intermedia, y la matriz de color convierte esa zona en opaca —
 * que es lo que produce el puente de líquido entre las dos.
 *
 * Los valores aleatorios se calculan una sola vez con `useMemo`. Si se
 * generaran en cada render, cada repintado movería las esferas de sitio.
 *
 * **`animado` decide si las esferas se mueven, y no es una preferencia
 * estética.** Cada fotograma de un fondo en movimiento obliga al navegador a
 * releer ese fondo por cada elemento con `backdrop-filter` que haya encima. En
 * el login hay una tarjeta y sale gratis; en el tablero hay quince, y encima
 * el fondo pasa por un filtro SVG a pantalla completa. Quieto, el mismo dibujo
 * se pinta una vez y no cuesta nada más.
 *
 * Quieto **no** significa en la posición inicial: la animación se pausa, y
 * como cada esfera arranca con un retraso negativo distinto, cada una se
 * congela en un punto distinto de su recorrido. La composición sale
 * repartida, igual que en movimiento, sin tener que colocarlas a mano.
 */

const CANTIDAD = 6;

export default function FondoBurbujas({ animado = true }) {
  const datos = useMemo(
    () => Array.from({ length: CANTIDAD }).map(() => ({
      tamano: Math.random() * 200 + 150,
      izquierda: Math.random() * 80 + 10,
      arriba: Math.random() * 80 + 10,
      retraso: Math.random() * -20,
      duracion: Math.random() * 15 + 15,
    })),
    []
  );

  const esferas = useRef([]);

  useEffect(() => {
    // Sin movimiento no hay paralaje: seguir el ratón para mover algo que
    // está congelado solo gastaría fotogramas.
    if (!animado) return undefined;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      return undefined;
    }

    let cuadro = null;
    let ultimo = { x: 0.5, y: 0.5 };

    const aplicar = () => {
      cuadro = null;
      esferas.current.forEach((esfera, i) => {
        if (!esfera) return;
        const fuerza = (i + 1) * 20;
        // **El paralaje va en `translate`, no en `margin`.**
        //
        // El original escribía `marginLeft` y `marginTop` para no pisar el
        // `transform` de la animación de flotado. El motivo es correcto —son
        // dos movimientos distintos sobre el mismo elemento— pero la solución
        // cuesta cara: el margen es una propiedad de maquetación, así que cada
        // movimiento del ratón obligaba al navegador a recalcular la posición
        // de todo, seis veces, dentro de un contenedor con un filtro SVG a
        // pantalla completa.
        //
        // `translate` es una propiedad propia, independiente de `transform`:
        // las dos se componen sin estorbarse, y ésta la resuelve el compositor
        // sin tocar la maquetación.
        esfera.style.translate = `${ultimo.x * fuerza}px ${ultimo.y * fuerza}px`;
      });
    };

    const alMover = (e) => {
      ultimo = {
        x: e.clientX / window.innerWidth,
        y: e.clientY / window.innerHeight,
      };
      // Un fotograma como mucho: el ratón dispara eventos mucho más rápido de
      // lo que la pantalla se refresca, y pintar de más no se ve.
      if (cuadro === null) cuadro = requestAnimationFrame(aplicar);
    };

    document.addEventListener('mousemove', alMover, { passive: true });
    return () => {
      document.removeEventListener('mousemove', alMover);
      if (cuadro !== null) cancelAnimationFrame(cuadro);
    };
  }, [animado]);

  return (
    <div
      className={`fondo-burbujas${animado ? '' : ' fondo-burbujas--quieto'}`}
      aria-hidden="true"
    >
      <div className="fondo-burbujas-escena">
        {datos.map((d, i) => (
          <div
            key={i}
            ref={(el) => { esferas.current[i] = el; }}
            /* Alternadas: par azul, impar rosa. Determinista y no al azar,
               para que las dos familias queden repartidas por la pantalla en
               vez de agruparse por casualidad. */
            className={`burbuja burbuja--${i % 2 === 0 ? 'azul' : 'rosa'}`}
            style={{
              width: `${d.tamano}px`,
              height: `${d.tamano}px`,
              left: `${d.izquierda}%`,
              top: `${d.arriba}%`,
              animationDelay: `${d.retraso}s`,
              animationDuration: `${d.duracion}s`,
            }}
          />
        ))}
      </div>
    </div>
  );
}
