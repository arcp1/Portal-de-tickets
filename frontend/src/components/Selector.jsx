import React, { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { ChevronDown, Check } from 'lucide-react';

/**
 * Un desplegable propio, en sustitución del `<select>` nativo.
 *
 * **Por qué existe.** El `<select>` se puede estilar cerrado, pero su lista
 * desplegable la dibuja el sistema operativo. Se llegó a que la lista saliera
 * oscura —Chrome sí respeta el `background-color` de las `<option>`— pero la
 * fila activa la pinta siempre con el color de resaltado de Windows, un azul
 * claro con texto negro que no se parece a nada del portal y que ninguna
 * regla de CSS puede tapar. Este componente es la única forma de que el
 * desplegable se vea como el resto.
 *
 * **Es un reemplazo directo.** Acepta los mismos `value`, `onChange`,
 * `className`, `style` y `disabled`, y las mismas `<option>` como hijas
 * —incluidas las que salen de un `.map()`—, así que migrar es cambiar el
 * nombre de la etiqueta. El `onChange` recibe un objeto con la forma
 * `{ target: { value } }` para que los manejadores existentes no cambien.
 *
 * **La lista va en un portal.** Media docena de contenedores del portal llevan
 * `overflow: hidden` —las tablas, las tarjetas de cristal— y una lista
 * posicionada dentro de ellos se recortaría. En el portal se posiciona con
 * coordenadas de viewport y se vuelca hacia arriba si abajo no cabe.
 *
 * Teclado: Enter, Espacio o flechas abren; las flechas, Inicio y Fin mueven;
 * Enter elige; Escape cierra; escribir salta a la opción que empieza así.
 */

/** Aplana hijos anidados y arrays de `.map()` hasta encontrar las `<option>`. */
function recogerOpciones(children, acc = []) {
  React.Children.forEach(children, (hijo) => {
    if (!React.isValidElement(hijo)) return;
    if (hijo.type === 'option') {
      acc.push({
        valor: hijo.props.value,
        etiqueta: React.Children.toArray(hijo.props.children).join(''),
        desactivada: !!hijo.props.disabled,
      });
    } else if (hijo.props && hijo.props.children) {
      recogerOpciones(hijo.props.children, acc);
    }
  });
  return acc;
}

export default function Selector({
  value,
  onChange,
  children,
  className = '',
  style,
  disabled = false,
  required = false,
  textoBoton,
  'aria-label': ariaLabel,
  id,
  ...resto
}) {
  const opciones = recogerOpciones(children);
  const elegida = opciones.find((o) => String(o.valor) === String(value));

  const [abierto, setAbierto] = useState(false);
  const [resaltada, setResaltada] = useState(-1);
  const [caja, setCaja] = useState(null);
  const disparador = useRef(null);
  const lista = useRef(null);
  const tecleo = useRef({ texto: '', reloj: 0 });
  const idLista = useId();

  const medir = useCallback(() => {
    const el = disparador.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const alto = Math.min(opciones.length * 38 + 12, 300);
    // Si abajo no cabe y arriba sí, se vuelca. Ocho píxeles de aire para que
    // la lista no quede pegada al borde de la ventana.
    const cabeAbajo = window.innerHeight - r.bottom - 8 >= alto;
    setCaja({
      izquierda: r.left,
      derecha: window.innerWidth - r.right,
      // Un disparador en la mitad derecha —el idioma, junto al borde— se
      // ancla por la derecha: la lista crece hacia dentro, no hacia fuera.
      anclarDerecha: r.left > window.innerWidth / 2,
      ancho: r.width,
      arriba: cabeAbajo ? r.bottom + 6 : null,
      abajo: cabeAbajo ? null : window.innerHeight - r.top + 6,
      altoMax: cabeAbajo ? window.innerHeight - r.bottom - 14 : r.top - 14,
    });
  }, [opciones.length]);

  useLayoutEffect(() => {
    if (!abierto) return undefined;
    medir();
    // `true` para capturar también el scroll de contenedores internos, que es
    // el que mueve el campo sin que la ventana se entere.
    const alMover = () => medir();
    window.addEventListener('scroll', alMover, true);
    window.addEventListener('resize', alMover);
    return () => {
      window.removeEventListener('scroll', alMover, true);
      window.removeEventListener('resize', alMover);
    };
  }, [abierto, medir]);

  useEffect(() => {
    if (!abierto) return undefined;
    const fuera = (e) => {
      if (disparador.current?.contains(e.target)) return;
      if (lista.current?.contains(e.target)) return;
      setAbierto(false);
    };
    document.addEventListener('mousedown', fuera);
    return () => document.removeEventListener('mousedown', fuera);
  }, [abierto]);

  useEffect(() => {
    if (!abierto || !lista.current) return;
    lista.current.querySelector('[data-resaltada="true"]')
      ?.scrollIntoView({ block: 'nearest' });
  }, [abierto, resaltada]);

  const abrir = () => {
    if (disabled) return;
    const i = opciones.findIndex((o) => String(o.valor) === String(value));
    setResaltada(i < 0 ? 0 : i);
    setAbierto(true);
  };

  const elegir = (opcion) => {
    setAbierto(false);
    disparador.current?.focus();
    if (opcion && String(opcion.valor) !== String(value)) {
      onChange?.({ target: { value: opcion.valor } });
      // Además del manejador, un `change` de verdad que burbujee. El objeto
      // que se pasa arriba imita la forma de un evento pero no es uno, así
      // que no sube por el árbol: sin esto, el `<Formulario>` que lo contiene
      // no se entera de que el campo ya está relleno y su aviso de validación
      // se quedaría puesto mientras la persona ya lo ha corregido.
      disparador.current?.dispatchEvent(new Event('change', { bubbles: true }));
    }
  };

  const mover = (paso) => {
    setResaltada((i) => {
      const n = opciones.length;
      let siguiente = i;
      for (let k = 0; k < n; k += 1) {
        siguiente = (siguiente + paso + n) % n;
        if (!opciones[siguiente].desactivada) return siguiente;
      }
      return i;
    });
  };

  const alTeclear = (e) => {
    if (disabled) return;
    const { key } = e;

    if (!abierto) {
      if (key === 'Enter' || key === ' ' || key === 'ArrowDown' || key === 'ArrowUp') {
        e.preventDefault();
        abrir();
      }
      return;
    }

    if (key === 'Escape') { e.preventDefault(); setAbierto(false); return; }
    if (key === 'Enter' || key === ' ') {
      e.preventDefault();
      elegir(opciones[resaltada]);
      return;
    }
    if (key === 'ArrowDown') { e.preventDefault(); mover(1); return; }
    if (key === 'ArrowUp') { e.preventDefault(); mover(-1); return; }
    if (key === 'Home') { e.preventDefault(); setResaltada(0); return; }
    if (key === 'End') { e.preventDefault(); setResaltada(opciones.length - 1); return; }
    if (key === 'Tab') { setAbierto(false); return; }

    // Salto por escritura: las pulsaciones seguidas se acumulan, así que
    // "im" encuentra "Impresora" y no se queda en la primera con "i".
    if (key.length === 1) {
      const ahora = Date.now();
      const texto = (ahora - tecleo.current.reloj < 800 ? tecleo.current.texto : '') + key.toLowerCase();
      tecleo.current = { texto, reloj: ahora };
      const i = opciones.findIndex(
        (o) => !o.desactivada && o.etiqueta.toLowerCase().startsWith(texto)
      );
      if (i >= 0) setResaltada(i);
    }
  };

  return (
    <>
      <button
        {...resto}
        id={id}
        ref={disparador}
        type="button"
        className={`selector ${className}`}
        style={style}
        disabled={disabled}
        /* `required` no significa nada en un `<button>`, así que el estado
           viaja en atributos de datos y lo valida `Formulario`. Sin esto, al
           dejar de ser un `<select>` estos campos se volvieron opcionales sin
           que nadie lo pidiera: un resguardo se podía emitir sin equipo. */
        data-requerido={required ? 'true' : undefined}
        data-valor={value ?? ''}
        aria-required={required || undefined}
        aria-haspopup="listbox"
        aria-expanded={abierto}
        aria-controls={abierto ? idLista : undefined}
        aria-label={ariaLabel}
        onClick={() => (abierto ? setAbierto(false) : abrir())}
        onKeyDown={alTeclear}
      >
        {/* `textoBoton` deja poner en el botón algo más corto que la opción:
            el selector de idioma enseña "ES" y reserva "Español" para la
            lista. En la barra esos cuarenta píxeles son la diferencia entre
            que se lea el nombre de quien ha entrado o no. */}
        <span className="selector-valor">
          {textoBoton ?? (elegida ? elegida.etiqueta : '')}
        </span>
        <ChevronDown size={16} className="selector-flecha" aria-hidden="true" />
      </button>

      {abierto && caja && createPortal(
        <ul
          ref={lista}
          id={idLista}
          role="listbox"
          className="selector-lista"
          style={{
            ...(caja.anclarDerecha ? { right: caja.derecha } : { left: caja.izquierda }),
            // Al menos el ancho del disparador, y lo que pidan las opciones.
            // Medía justo lo del disparador, y en uno compacto —el "ES" del
            // idioma— los nombres salían cortados: "Españ", "Englis".
            minWidth: caja.ancho,
            width: 'max-content',
            maxWidth: 'calc(100vw - 16px)',
            ...(caja.arriba !== null ? { top: caja.arriba } : { bottom: caja.abajo }),
            maxHeight: caja.altoMax,
          }}
        >
          {opciones.map((o, i) => (
            <li
              key={`${o.valor}`}
              role="option"
              aria-selected={String(o.valor) === String(value)}
              aria-disabled={o.desactivada || undefined}
              data-resaltada={i === resaltada}
              className={[
                'selector-opcion',
                i === resaltada ? 'selector-opcion--resaltada' : '',
                String(o.valor) === String(value) ? 'selector-opcion--elegida' : '',
                o.desactivada ? 'selector-opcion--desactivada' : '',
              ].filter(Boolean).join(' ')}
              onMouseEnter={() => !o.desactivada && setResaltada(i)}
              onClick={() => !o.desactivada && elegir(o)}
            >
              <span>{o.etiqueta}</span>
              {String(o.valor) === String(value) && <Check size={15} aria-hidden="true" />}
            </li>
          ))}
        </ul>,
        document.body
      )}
    </>
  );
}
