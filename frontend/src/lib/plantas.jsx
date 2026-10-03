import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Check, Factory } from 'lucide-react';
import api from '../api/client';
import lista from './lista';
import Selector from '../components/Selector';

/**
 * Las plantas, para todo el portal.
 *
 * **Quién ve qué** (el backend lo decide; ver backend/app/core/plantas.py):
 * TI es global y recibe todas las plantas activas; una persona de planta, solo
 * las suyas. Así el mismo selector sirve a los dos: a una persona con una
 * sola planta ni se le enseña —no hay nada que elegir—.
 *
 * Se piden una vez por sesión y se comparten: las cambian muy pocas veces y
 * cinco pantallas pidiendo lo mismo al montar son cinco viajes de más. La
 * pantalla de Plantas, al guardar, llama a `olvidarPlantas()`.
 */
let enCache = null;
let pidiendo = null;
let deQuien = null;

export function olvidarPlantas() {
  enCache = null;
  pidiendo = null;
}

function pedirPlantas() {
  const quien = localStorage.getItem('portal_tickets_token');
  if (enCache && deQuien === quien) return Promise.resolve(enCache);
  if (pidiendo && deQuien === quien) return pidiendo;
  deQuien = quien;
  pidiendo = api.get('/sitios')
    .then((res) => { enCache = lista(res.data, 'las plantas'); return enCache; })
    .catch(() => { pidiendo = null; return []; });
  return pidiendo;
}

/** `[plantas, cargando]`. */
export function usePlantas() {
  const [plantas, setPlantas] = useState(enCache || []);
  const [cargando, setCargando] = useState(!enCache);
  useEffect(() => {
    let vivo = true;
    pedirPlantas().then((p) => { if (vivo) { setPlantas(p); setCargando(false); } });
    return () => { vivo = false; };
  }, []);
  return [plantas, cargando];
}

/** La etiqueta de planta de un ticket o un equipo: clave corta, nombre al pasar el ratón. */
export function EtiquetaPlanta({ planta, compacta = false }) {
  if (!planta) return null;
  return (
    <span className="chip-dato chip-planta" title={planta.nombre}>
      <Factory size={12} aria-hidden="true" />
      {compacta ? planta.clave : `${planta.clave} · ${planta.nombre}`}
    </span>
  );
}

/**
 * Elegir planta. `todas` añade la opción vacía ("Todas las plantas"), para
 * filtros; sin ella es un campo de formulario.
 */
export function SelectorPlanta({
  value, onChange, plantas, todas = false, required = false, disabled = false,
  className = 'form-select', style, id, 'aria-label': ariaLabel,
}) {
  const { t } = useTranslation();
  return (
    <Selector
      id={id}
      className={className}
      style={style}
      value={value == null ? '' : String(value)}
      onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}
      disabled={disabled}
      required={required}
      aria-label={ariaLabel || t('plantas.planta')}
    >
      {todas
        ? <option value="">{t('plantas.todas')}</option>
        : <option value="" disabled>{t('plantas.elegir')}</option>}
      {plantas.map((p) => (
        <option key={p.id} value={String(p.id)}>{`${p.clave} · ${p.nombre}`}</option>
      ))}
    </Selector>
  );
}

/** Lo que se lee bajo el nombre del portal: "TI · todas las plantas" o las de la persona. */
export function textoPlantasDe(usuario, t) {
  if (!usuario) return '';
  if (usuario.es_ti_global || usuario.rol === 'admin') return t('plantas.ti_global');
  const suyas = lista(usuario.plantas, 'las plantas de la persona');
  if (suyas.length > 1) return suyas.map((p) => p.clave).join(' · ');
  if (suyas.length === 1) return suyas[0].nombre;
  return usuario.sitio_nombre || '';
}

/**
 * Elegir varias plantas: una persona puede trabajar en más de una. La
 * primera elegida es la principal —la que se le propone al levantar un
 * ticket— y se marca. Son casillas de verdad, para el teclado y el lector.
 */
export function PlantasMultiples({ plantas, value, onChange, idGrupo = 'plantas-persona' }) {
  const { t } = useTranslation();
  const elegidas = value || [];
  const alternar = (id) => {
    onChange(elegidas.includes(id) ? elegidas.filter((x) => x !== id) : [...elegidas, id]);
  };
  return (
    <div className="plantas-multiples" role="group" aria-labelledby={`${idGrupo}-rotulo`}>
      {plantas.map((p) => {
        const marcada = elegidas.includes(p.id);
        return (
          <label key={p.id} className={`chip-filtro${marcada ? ' chip-filtro--activo' : ''}`}>
            <input type="checkbox" className="solo-lectores" checked={marcada}
              onChange={() => alternar(p.id)} />
            {/* La palomita dice "marcada" sin depender del color del chip,
                que en el diálogo oscuro apenas se distinguía. */}
            {marcada ? <Check size={13} aria-hidden="true" /> : <Factory size={13} aria-hidden="true" />}
            {p.clave} · {p.nombre}
            {marcada && elegidas[0] === p.id && elegidas.length > 1 && (
              <span className="plantas-principal">{t('plantas.principal')}</span>
            )}
          </label>
        );
      })}
    </div>
  );
}
