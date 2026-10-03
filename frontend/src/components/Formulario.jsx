import React, { useCallback, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle } from 'lucide-react';

/**
 * Un `<form>` que avisa con nuestras palabras cuando falta algo.
 *
 * **Por qué existe.** El navegador ya valida los campos `required`, pero el
 * globo que enseña lo dibuja el sistema operativo: no se puede estilar, sale
 * en el idioma de Chrome y no en el del portal —"Please fill out this
 * field"—, y solo señala un campo cada vez, así que en un formulario con tres
 * huecos hay que enviarlo tres veces para enterarse de todos. Es el mismo
 * problema que tenía el desplegable nativo.
 *
 * Aquí se apaga esa validación con `noValidate` y se usa la API que hay
 * debajo —`checkValidity`, `validity`— para construir el aviso nosotros: uno
 * solo, arriba del formulario, nombrando **todos** los campos que faltan, y
 * con esos campos marcados en rojo. El primero recibe el foco.
 *
 * **Los nombres salen de las etiquetas que ya hay.** No hace falta declarar
 * nada por campo: se busca el `<label>` que le corresponde, en las dos formas
 * en que el portal envuelve un campo. Ver `nombreDe` más abajo.
 *
 * **También valida los desplegables propios**, que el navegador no ve. Desde
 * que `<select>` pasó a ser `Selector` —un `<button>`— su `required` dejó de
 * significar nada para la validación nativa: un resguardo se podía enviar sin
 * equipo y sin persona. `Selector` publica su estado en `data-requerido` y
 * `data-valor`, y aquí se comprueban igual que los campos de verdad.
 */

/** El nombre legible de un campo, sacado de lo que ya está escrito.
 *
 *  Se buscan varias formas porque el portal tiene dos maneras de envolver un
 *  campo: `.form-group` en las pantallas de trabajo y `.campo-linea` en la
 *  puerta, donde los campos son solo una raya. Mirando únicamente la primera,
 *  el login decía "Falta escribir identificador" —el `name` del `<input>`— en
 *  vez de "Número de empleado". El último recurso es un texto genérico: más
 *  vale eso que enseñar el nombre técnico de un campo. */
function nombreDe(el, t) {
  const id = el.getAttribute('id');
  const bruto =
    (id && document.querySelector(`label[for="${CSS.escape(id)}"]`)?.textContent)
    || el.closest('label')?.textContent
    || el.closest('.form-group, .campo-linea')?.querySelector('label')?.textContent
    || el.getAttribute('aria-label')
    || el.getAttribute('placeholder');
  if (!bruto) return t('validacion.campo_sin_nombre');
  // Las etiquetas suelen acabar en dos puntos o asterisco de obligatorio.
  return bruto.trim().replace(/\s*[:*]+\s*$/, '');
}

function recogerFallos(form, t) {
  const fallos = [];

  for (const el of Array.from(form.elements)) {
    if (!el.willValidate || el.disabled || el.checkValidity()) continue;
    const campo = nombreDe(el, t);
    const v = el.validity;
    let mensaje;
    if (v.valueMissing) mensaje = t('validacion.falta', { campo });
    else if (v.typeMismatch && el.type === 'email') mensaje = t('validacion.correo', { campo });
    else if (v.tooShort) mensaje = t('validacion.corto', { campo, min: el.minLength });
    else if (v.rangeUnderflow || v.rangeOverflow) mensaje = t('validacion.rango', { campo });
    else mensaje = t('validacion.invalido', { campo });
    fallos.push({ el, campo, mensaje });
  }

  // Los desplegables propios: el navegador no los cuenta como campos.
  form.querySelectorAll('[data-requerido="true"]').forEach((el) => {
    if (el.dataset.valor) return;
    const campo = nombreDe(el, t);
    fallos.push({ el, campo, mensaje: t('validacion.falta', { campo }) });
  });

  return fallos;
}

export default function Formulario({ onSubmit, children, ...resto }) {
  const { t } = useTranslation();
  const ref = useRef(null);
  const [fallos, setFallos] = useState([]);

  const limpiarMarcas = useCallback(() => {
    ref.current?.querySelectorAll('.campo-invalido')
      .forEach((el) => el.classList.remove('campo-invalido'));
  }, []);

  const enviar = (e) => {
    const form = ref.current;
    if (!form) return;
    const encontrados = recogerFallos(form, t);

    limpiarMarcas();
    if (encontrados.length > 0) {
      e.preventDefault();
      encontrados.forEach(({ el }) => el.classList.add('campo-invalido'));
      setFallos(encontrados);
      const primero = encontrados[0].el;
      primero.focus({ preventScroll: true });
      primero.scrollIntoView({ block: 'center', behavior: 'smooth' });
      return;
    }

    setFallos([]);
    onSubmit?.(e);
  };

  // En cuanto se toca cualquier cosa se retira el aviso: dejarlo puesto
  // mientras la persona ya está corrigiendo lo convierte en ruido.
  const alTocar = () => {
    if (fallos.length === 0) return;
    setFallos([]);
    limpiarMarcas();
  };

  return (
    <form
      {...resto}
      ref={ref}
      noValidate
      onSubmit={enviar}
      onInput={alTocar}
      onChange={alTocar}
    >
      {fallos.length > 0 && (
        <div className="aviso-validacion animate-scale-in" role="alert">
          <AlertTriangle size={17} aria-hidden="true" />
          <div>
            <strong>{t('validacion.titulo')}</strong>
            <ul>
              {fallos.map(({ campo, mensaje }) => (
                <li key={campo}>{mensaje}</li>
              ))}
            </ul>
          </div>
        </div>
      )}
      {children}
    </form>
  );
}
