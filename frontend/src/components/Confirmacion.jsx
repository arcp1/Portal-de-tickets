import React, { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, Check, X } from 'lucide-react';
import CapaModal from './CapaModal';
import Formulario from './Formulario';

/**
 * La pregunta de "¿seguro?" dentro de la interfaz.
 *
 * **El problema que resuelve.** `window.confirm` y `window.prompt` congelan
 * el hilo del renderizador: mientras la ventana del navegador está abierta,
 * React no pinta nada y las peticiones que estaban en vuelo se quedan
 * esperando. Encima salen con el aspecto del navegador —tipografía, idioma
 * del sistema, el nombre del host arriba—, así que en un portal traducido a
 * tres idiomas aparecen botones "OK/Cancelar" en el idioma del equipo, no en
 * el que la persona eligió. Y en Chrome, repetirlas ofrece "impedir que esta
 * página abra más diálogos": a partir de ahí `confirm()` devuelve `false`
 * siempre y la acción deja de funcionar sin decir por qué.
 *
 * Esto es lo mismo pero pintado por nosotros: hereda el velo, el centrado, el
 * cierre con Escape y el bloqueo del scroll de [[CapaModal]], y el texto pasa
 * por `t(...)` como el resto del portal.
 *
 * Con `campo` hace además el papel de `window.prompt`: muestra un cuadro de
 * texto y entrega su valor a `onConfirmar`. Sin `campo`, `onConfirmar` se
 * llama sin argumentos.
 */
export default function Confirmacion({
  titulo,
  mensaje,
  textoConfirmar,
  textoCancelar,
  tono = 'normal',
  campo = null,
  onConfirmar,
  onCancelar
}) {
  const { t } = useTranslation();
  const [valor, setValor] = useState(campo?.valorInicial || '');
  const primerFoco = useRef(null);

  // El foco entra en la ventana: quien usa teclado no tiene que buscarla, y
  // Enter confirma como en cualquier diálogo.
  useEffect(() => {
    primerFoco.current?.focus();
  }, []);

  const peligro = tono === 'peligro';
  // Un campo vacío no vale como respuesta: es lo que hacía el `!nuevo.trim()`
  // de antes, solo que ahora el botón lo dice en vez de cerrarse sin más.
  const vacio = campo && !valor.trim();

  const enviar = (e) => {
    e.preventDefault();
    if (vacio) return;
    onConfirmar(campo ? valor.trim() : undefined);
  };

  return (
    <CapaModal onCerrar={onCancelar} etiqueta={titulo}>
      <Formulario
        onSubmit={enviar}
        onClick={(e) => e.stopPropagation()}
        className="apple-card animate-scale-in"
        style={{ padding: '30px', maxWidth: '440px', width: '100%' }}
      >
        <div style={{ display: 'flex', gap: '14px', marginBottom: campo ? '18px' : '24px' }}>
          <AlertTriangle
            size={22}
            style={{ flexShrink: 0, marginTop: '2px' }}
            color={peligro ? 'var(--peligro)' : 'var(--status-espera-proveedor-text)'}
          />
          <div>
            <h2 style={{ fontSize: '1.1rem', fontWeight: '700', color: 'var(--text-primary)', lineHeight: 1.35 }}>
              {titulo}
            </h2>
            {mensaje && (
              <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', lineHeight: 1.5, marginTop: '8px' }}>
                {mensaje}
              </p>
            )}
          </div>
        </div>

        {campo && (
          <div className="form-group" style={{ marginBottom: '22px' }}>
            {campo.etiqueta && <label>{campo.etiqueta}</label>}
            <input
              ref={primerFoco}
              className="form-input"
              value={valor}
              placeholder={campo.placeholder || ''}
              onChange={(e) => setValor(e.target.value)}
            />
          </div>
        )}

        <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
          <button type="button" onClick={onCancelar} className="btn-secondary" style={{ padding: '10px 18px' }}>
            <X size={15} /> {textoCancelar || t('comun.cancelar')}
          </button>
          <button
            type="submit"
            ref={campo ? undefined : primerFoco}
            disabled={vacio}
            className={`btn-primary ${peligro ? 'btn-primary--peligro' : ''}`}
            style={{ padding: '10px 18px' }}
          >
            <Check size={15} /> {textoConfirmar || t('comun.confirmar')}
          </button>
        </div>
      </Formulario>
    </CapaModal>
  );
}
