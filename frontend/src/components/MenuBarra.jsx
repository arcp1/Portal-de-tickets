import React, { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Link } from 'react-router-dom';
import { ChevronDown } from 'lucide-react';

/**
 * Un grupo de secciones de la barra, plegado en un menú.
 *
 * **Por qué existe.** Un administrador tiene trece secciones. Puestas en fila
 * no caben con su nombre, así que se quedaban en trece iconos sueltos sin
 * texto: para saber cuál era cuál había que pasar el ratón por encima y
 * esperar el tooltip, uno por uno. Agrupadas quedan seis entradas y vuelven a
 * poder leerse.
 *
 * **El botón del grupo se marca cuando la sección abierta está dentro.** Sin
 * eso se pierde el "usted está aquí": el enlace activo dejaría de verse en la
 * barra en cuanto viviera dentro de un menú.
 *
 * La lista va en un portal por lo mismo que la del desplegable: la barra
 * lleva `backdrop-filter` y sus contenedores recortan, y un panel dibujado
 * dentro se cortaría contra el borde inferior.
 */
export default function MenuBarra({
  texto,
  entradas,
  rutaActiva,
  claseBoton = 'navbar-enlace navbar-grupo',
  contenido,
  alinear = 'izquierda',
}) {
  const [abierto, setAbierto] = useState(false);
  const [caja, setCaja] = useState(null);
  const disparador = useRef(null);
  const panel = useRef(null);
  const idPanel = useId();

  const contieneActiva = entradas.some((e) => e.ruta && e.ruta === rutaActiva);

  const medir = useCallback(() => {
    const el = disparador.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    // El menú del perfil vive pegado al borde derecho, así que se cuelga por
    // ese lado: alineado por la izquierda se saldría de la ventana.
    setCaja({
      izquierda: alinear === 'derecha' ? null : r.left,
      derecha: alinear === 'derecha' ? window.innerWidth - r.right : null,
      arriba: r.bottom + 8,
      anchoMin: r.width,
    });
  }, [alinear]);

  useLayoutEffect(() => {
    if (!abierto) return undefined;
    medir();
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
      if (panel.current?.contains(e.target)) return;
      setAbierto(false);
    };
    const tecla = (e) => {
      if (e.key === 'Escape') { setAbierto(false); disparador.current?.focus(); }
    };
    document.addEventListener('mousedown', fuera);
    document.addEventListener('keydown', tecla);
    return () => {
      document.removeEventListener('mousedown', fuera);
      document.removeEventListener('keydown', tecla);
    };
  }, [abierto]);

  return (
    <>
      <button
        ref={disparador}
        type="button"
        className={`${claseBoton}${contieneActiva ? ' activo' : ''}`}
        aria-haspopup="true"
        aria-expanded={abierto}
        aria-controls={abierto ? idPanel : undefined}
        onClick={() => setAbierto((v) => !v)}
      >
        {/* Sin icono, al contrario que los enlaces sueltos: el nombre del
            grupo ya lo dice, y esos 26 px por cuatro grupos son justo lo que
            hacía falta para que el texto de todos cupiera junto a la marca y
            al perfil. Los iconos siguen dentro del panel, donde sí ayudan a
            distinguir secciones entre sí. */}
        {contenido || <span className="navbar-enlace-texto navbar-grupo-texto">{texto}</span>}
        <ChevronDown size={14} className="navbar-grupo-flecha" aria-hidden="true" />
      </button>

      {abierto && caja && createPortal(
        <div
          ref={panel}
          id={idPanel}
          className="navbar-grupo-panel"
          style={{
            ...(caja.izquierda !== null ? { left: caja.izquierda } : { right: caja.derecha }),
            top: caja.arriba,
            minWidth: Math.max(caja.anchoMin, 210),
          }}
        >
          {entradas.map((e) => {
            const clases = [
              'navbar-grupo-opcion',
              e.ruta === rutaActiva ? 'navbar-grupo-opcion--activa' : '',
              e.peligro ? 'navbar-grupo-opcion--peligro' : '',
            ].filter(Boolean).join(' ');
            // Una entrada es un enlace o una acción; en el menú del perfil
            // conviven las dos —"Mi Expediente" navega, "Cerrar sesión" no—.
            // O solo una nota: lo que conviene saber y no se pulsa.
            if (e.nota) {
              return (
                <div key={e.texto} className={`${clases} navbar-grupo-opcion--nota`} role="note">
                  {e.icono}
                  <span>{e.texto}</span>
                </div>
              );
            }
            if (e.ruta) {
              return (
                <Link viewTransition key={e.ruta} to={e.ruta} className={clases}
                  onClick={() => setAbierto(false)}>
                  {e.icono}
                  <span>{e.texto}</span>
                </Link>
              );
            }
            return (
              <button key={e.texto} type="button" className={clases}
                onClick={() => { setAbierto(false); e.onSelect(); }}>
                {e.icono}
                <span>{e.texto}</span>
              </button>
            );
          })}
        </div>,
        document.body
      )}
    </>
  );
}
