import React, { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Search, CornerDownLeft, Hash, LogOut, KeyRound, Languages, User } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { seccionesDe, aplanarSecciones } from '../lib/navegacion';
import { cambiarIdioma as cambiarIdiomaDelPortal } from '../i18n';

/**
 * La paleta de comandos: `Ctrl+K` y se va a cualquier sitio sin soltar el
 * teclado.
 *
 * **Por qué.** Un administrador tiene trece secciones y nueve de ellas viven
 * dentro de un menú plegado, porque en fila no caben con su nombre. Llegar a
 * "Documentación" son dos clics y saber de antemano que está en el cajón de
 * Conocimiento. Escribir "docu" no pide saber nada.
 *
 * **Qué hace.** Lleva a las secciones que esa persona tiene —las mismas que
 * la barra, de `lib/navegacion`, para que no puedan desincronizarse—, abre un
 * ticket por su número y deja a mano lo de la cuenta: expediente, contraseña,
 * idioma y salir.
 *
 * **La coincidencia es por subsecuencia, no por prefijo.** "dcm" encuentra
 * "Documentación" y "est sis" encuentra "Estado del sistema": lo que se
 * escribe en una paleta son las consonantes que uno recuerda, no el principio
 * exacto del nombre. Y se puntúa: las coincidencias seguidas y las que caen
 * al principio de una palabra valen más, así que escribir "es" pone "Estado"
 * por delante de "Personas", que también contiene una 'e' y una 's'.
 */

/** Sin tildes y en minúscula: quien teclea rápido no pone los acentos. */
function normalizar(s) {
  return s.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
}

/**
 * Puntúa `consulta` contra `texto`. Devuelve `null` si no está contenida como
 * subsecuencia; si no, cuanto más alto, mejor.
 */
function puntuar(texto, consulta) {
  const t = normalizar(texto);
  const q = normalizar(consulta);
  if (!q) return 0;

  let punt = 0;
  let desde = 0;
  let anterior = -2;
  for (const letra of q) {
    const i = t.indexOf(letra, desde);
    if (i < 0) return null;
    // Letra pegada a la anterior: es una palabra escrita de verdad, no letras
    // sueltas que casualmente aparecen repartidas por el nombre.
    if (i === anterior + 1) punt += 6;
    // Principio de palabra: "es" en "Estado del sistema" vale más que la 'e'
    // que hay en medio de "Personas".
    if (i === 0 || /[\s/·-]/.test(t[i - 1])) punt += 4;
    punt += 1;
    anterior = i;
    desde = i + 1;
  }
  // A igualdad de coincidencia, el nombre más corto es el que se buscaba.
  return punt - t.length * 0.06;
}

export default function PaletaComandos() {
  const { t, i18n } = useTranslation();
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const [abierta, setAbierta] = useState(false);
  const [consulta, setConsulta] = useState('');
  const [resaltada, setResaltada] = useState(0);
  const campo = useRef(null);
  const lista = useRef(null);
  const focoPrevio = useRef(null);
  const idLista = useId();

  const cerrar = useCallback(() => {
    setAbierta(false);
    setConsulta('');
    setResaltada(0);
  }, []);

  const cambiarIdioma = useCallback((codigo) => { cambiarIdiomaDelPortal(codigo); }, []);

  // Todo lo que la paleta sabe hacer, antes de filtrar.
  const comandos = useMemo(() => {
    if (!user) return [];
    const esAdmin = user.rol === 'admin';
    const secciones = aplanarSecciones(seccionesDe(t, esAdmin)).map((s) => ({
      id: 'ir:' + s.ruta,
      icono: s.icono,
      texto: s.texto,
      pista: s.grupo,
      grupo: t('paleta.grupo_ir'),
      hacer: () => navigate(s.ruta)
    }));

    const cuenta = [
      {
        id: 'expediente',
        icono: <User size={16} />,
        texto: t('nav.expediente'),
        grupo: t('paleta.grupo_cuenta'),
        hacer: () => navigate('/expediente')
      },
      {
        id: 'password',
        icono: <KeyRound size={16} />,
        texto: t('password.abrir'),
        grupo: t('paleta.grupo_cuenta'),
        // La paleta no sabe abrir el diálogo de contraseña, que vive dentro
        // de la barra. Lo pide por evento y la barra lo abre: es preferible a
        // subir ese estado a la aplicación entera por un atajo.
        hacer: () => window.dispatchEvent(new CustomEvent('portal:cambiar-password'))
      },
      ...[['es', 'Español'], ['en', 'English'], ['fr', 'Français']].map(([codigo, nombre]) => ({
        id: 'idioma:' + codigo,
        icono: <Languages size={16} />,
        texto: t('paleta.idioma', { idioma: nombre }),
        grupo: t('paleta.grupo_cuenta'),
        activo: i18n.language === codigo,
        hacer: () => cambiarIdioma(codigo)
      })),
      {
        id: 'salir',
        icono: <LogOut size={16} />,
        texto: t('nav.logout'),
        grupo: t('paleta.grupo_cuenta'),
        peligro: true,
        hacer: () => { logout(); navigate('/login', { replace: true }); }
      }
    ];

    return [...secciones, ...cuenta];
  }, [user, t, i18n.language, navigate, logout, cambiarIdioma]);

  const resultados = useMemo(() => {
    const q = consulta.trim();

    // Un número es un ticket. Se ofrece antes que nada: quien escribe "482"
    // en una paleta va a un ticket, no a una sección que lleve un 4 en el
    // nombre. El folio completo también vale — se le saca la parte numérica.
    const extra = [];
    const soloDigitos = q.replace(/^#/, '').match(/^(?:tick[\s/-]*\w*[\s/-]*\d{4}[\s/-]*)?(\d{1,7})$/i);
    if (soloDigitos) {
      const numero = String(Number(soloDigitos[1]));
      extra.push({
        id: 'ticket:' + numero,
        icono: <Hash size={16} />,
        texto: t('paleta.abrir_ticket', { n: numero }),
        grupo: t('paleta.grupo_ir'),
        hacer: () => navigate('/tickets/' + numero)
      });
    }

    if (!q) return [...extra, ...comandos];

    const conPuntos = [];
    for (const c of comandos) {
      // Se puntúa también contra el nombre del grupo, así "sistema" saca
      // todo lo que vive en ese cajón aunque ninguno se llame así.
      const p = puntuar(c.texto, q);
      const pg = c.pista ? puntuar(c.pista, q) : null;
      const mejor = p === null ? (pg === null ? null : pg - 3) : p;
      if (mejor !== null) conPuntos.push([mejor, c]);
    }
    conPuntos.sort((a, b) => b[0] - a[0]);
    return [...extra, ...conPuntos.map(([, c]) => c)];
  }, [consulta, comandos, navigate, t]);

  // Abrir y cerrar. `Ctrl+K` y `Cmd+K` en el Mac; `Escape` cierra.
  useEffect(() => {
    const alPulsar = (e) => {
      if ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K')) {
        e.preventDefault();
        setAbierta((v) => !v);
        setConsulta('');
        setResaltada(0);
      }
    };
    // El botón de la barra la abre sin atajo, para quien no lo conozca.
    const abrir = () => { setAbierta(true); setConsulta(''); setResaltada(0); };
    document.addEventListener('keydown', alPulsar);
    window.addEventListener('portal:paleta', abrir);
    return () => {
      document.removeEventListener('keydown', alPulsar);
      window.removeEventListener('portal:paleta', abrir);
    };
  }, []);

  /* **Al cerrar, el foco vuelve de donde vino.** Sin esto se queda en el
     `body`: quien abrió la paleta con el teclado desde una tabla pierde el
     sitio y tiene que tabular desde el principio de la página.

     Y mientras está abierta el fondo no se desplaza —la rueda del ratón sobre
     el velo movería la página de detrás, que es de lo más desconcertante que
     puede hacer un diálogo—. */
  useEffect(() => {
    if (!abierta) return undefined;
    focoPrevio.current = document.activeElement;
    campo.current?.focus();
    const overflowPrevio = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = overflowPrevio;
      const volver = focoPrevio.current;
      if (volver && document.contains(volver)) volver.focus?.();
    };
  }, [abierta]);

  useEffect(() => { setResaltada(0); }, [consulta]);

  useEffect(() => {
    if (!abierta) return;
    lista.current?.querySelector('[data-resaltada="true"]')
      ?.scrollIntoView({ block: 'nearest' });
  }, [abierta, resaltada]);

  if (!user || !abierta) return null;

  const ejecutar = (c) => {
    if (!c) return;
    cerrar();
    c.hacer();
  };

  const alTeclear = (e) => {
    if (e.key === 'Escape') { e.preventDefault(); cerrar(); return; }
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setResaltada((i) => (resultados.length ? (i + 1) % resultados.length : 0));
      return;
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault();
      setResaltada((i) => (resultados.length ? (i - 1 + resultados.length) % resultados.length : 0));
      return;
    }
    if (e.key === 'Enter') { e.preventDefault(); ejecutar(resultados[resaltada]); }
  };

  return createPortal(
    <div className="paleta-fondo" onMouseDown={cerrar} role="presentation">
      {/* El clic dentro no cierra; el de fuera sí. */}
      <div
        className="paleta"
        role="dialog"
        aria-modal="true"
        aria-label={t('paleta.titulo')}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="paleta-campo">
          <Search size={17} aria-hidden="true" />
          <input
            ref={campo}
            type="text"
            value={consulta}
            onChange={(e) => setConsulta(e.target.value)}
            onKeyDown={alTeclear}
            placeholder={t('paleta.marcador')}
            aria-label={t('paleta.marcador')}
            autoComplete="off"
            spellCheck="false"
            /* El foco no se mueve de aquí nunca: las flechas cambian cuál está
               resaltada, no cuál tiene el foco. Sin `aria-activedescendant`
               un lector de pantalla no anuncia ese cambio y la lista es muda
               para quien no la ve. */
            role="combobox"
            aria-expanded="true"
            aria-controls={idLista}
            aria-activedescendant={resultados[resaltada] ? `${idLista}-${resaltada}` : undefined}
          />
          <kbd className="paleta-tecla">ESC</kbd>
        </div>

        {resultados.length === 0 ? (
          <div className="paleta-vacia">{t('paleta.sin_resultados', { q: consulta })}</div>
        ) : (
          <ul className="paleta-lista" ref={lista} id={idLista} role="listbox" aria-label={t('paleta.titulo')}>
            {resultados.map((c, i) => {
              // El nombre del grupo se escribe una sola vez, en la primera
              // fila que le pertenece; repetirlo en cada línea convierte la
              // lista en una columna de la misma palabra.
              const nuevoGrupo = i === 0 || resultados[i - 1].grupo !== c.grupo;
              return (
                <React.Fragment key={c.id}>
                  {nuevoGrupo && <li className="paleta-grupo" role="presentation">{c.grupo}</li>}
                  <li
                    id={`${idLista}-${i}`}
                    role="option"
                    aria-selected={i === resaltada}
                    data-resaltada={i === resaltada}
                    className={[
                      'paleta-opcion',
                      i === resaltada ? 'paleta-opcion--resaltada' : '',
                      c.peligro ? 'paleta-opcion--peligro' : ''
                    ].filter(Boolean).join(' ')}
                    onMouseEnter={() => setResaltada(i)}
                    onClick={() => ejecutar(c)}
                  >
                    {c.icono}
                    <span className="paleta-texto">{c.texto}</span>
                    {c.pista && <span className="paleta-pista">{c.pista}</span>}
                    {c.activo && <span className="paleta-pista">●</span>}
                    {i === resaltada && <CornerDownLeft size={14} aria-hidden="true" />}
                  </li>
                </React.Fragment>
              );
            })}
          </ul>
        )}

        {/* **Las teclas, a la vista.** Quien abre una paleta por primera vez
            prueba a escribir y luego se queda sin saber si las flechas
            sirven. Tres pares de tecla y verbo lo resuelven sin explicar
            nada. */}
        <div className="paleta-pie">
          <span><kbd>↑</kbd><kbd>↓</kbd> {t('paleta.navegar')}</span>
          <span><kbd>⏎</kbd> {t('paleta.abrir')}</span>
          <span><kbd>esc</kbd> {t('paleta.cerrar')}</span>
        </div>
      </div>
    </div>,
    document.body
  );
}
