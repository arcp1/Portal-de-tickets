import React, { useState, useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import api from '../api/client';
import { FileSignature, X, Check, AlertTriangle, Download } from 'lucide-react';
import CapaModal from './CapaModal';
import Formulario from './Formulario';

/**
 * Firma de un resguardo.
 *
 * Se pide teclear el nombre completo en vez de solo un clic: convierte la
 * aceptación en un acto deliberado y deja constancia de qué escribió la
 * persona. Junto con la IP y la hora, es lo que hace que el documento sirva.
 *
 * Las condiciones se muestran completas antes de poder aceptar. Nadie firma
 * algo que no se le enseñó.
 */
const FirmaResguardo = ({ resguardo, nombreSugerido, onFirmado, onCerrar }) => {
  const { t } = useTranslation();
  const [nombre, setNombre] = useState('');
  const [acepto, setAcepto] = useState(false);
  const [leyoTodo, setLeyoTodo] = useState(false);
  const cajaCondiciones = useRef(null);

  // Unas condiciones cortas no desbordan la caja, el evento de scroll nunca
  // dispara y la casilla de aceptacion se quedaba deshabilitada para siempre:
  // la persona no podia firmar de ninguna manera. Si no hay nada que
  // desplazar, ya lo leyo todo.
  useEffect(() => {
    const caja = cajaCondiciones.current;
    if (!caja) return;
    if (caja.scrollHeight - caja.clientHeight < 40) setLeyoTodo(true);
  }, [resguardo.condiciones]);
  const [enviando, setEnviando] = useState(false);
  const [error, setError] = useState('');

  const nombreValido = nombre.trim().length >= 3;
  const puedeFirmar = nombreValido && acepto && leyoTodo && !enviando;

  const firmar = async (e) => {
    e.preventDefault();
    if (!puedeFirmar) return;
    setEnviando(true);
    setError('');
    try {
      const res = await api.post(`/resguardos/${resguardo.id}/firmar`, {
        nombre_completo: nombre.trim(),
        acepto: true
      });
      onFirmado?.(res.data);
    } catch (err) {
      setError(err.response?.data?.detail || t('resguardos.error_firmar'));
      setEnviando(false);
    }
  };

  const verPdf = async () => {
    try {
      const res = await api.get(`/resguardos/${resguardo.id}/pdf`, { responseType: 'blob' });
      const url = URL.createObjectURL(res.data);
      window.open(url, '_blank', 'noopener,noreferrer');
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch {
      setError(t('resguardos.error_pdf'));
    }
  };

  return (
    <CapaModal onCerrar={onCerrar}>
      <Formulario
        onClick={(e) => e.stopPropagation()}
        onSubmit={firmar}
        className="apple-card animate-scale-in"
        style={{ padding: '32px', maxWidth: '720px', width: '100%', maxHeight: '92vh', overflowY: 'auto' }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '16px', marginBottom: '6px' }}>
          <h2 style={{ fontSize: '1.3rem', fontWeight: '700', color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '10px' }}>
            <FileSignature size={22} color="var(--accent-primary)" />
            {t('resguardos.firmar_titulo')}
          </h2>
          <button type="button" onClick={onCerrar} className="btn-secondary"
            style={{ padding: '6px 10px' }} aria-label={t('temas.cancelar')}>
            <X size={16} />
          </button>
        </div>

        <div style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', marginBottom: '20px' }}>
          {t('resguardos.folio')}: <strong style={{ color: 'var(--accent-primary)' }}>{resguardo.folio}</strong>
        </div>

        {/* Qué se está recibiendo */}
        {resguardo.equipo && (
          <div style={{
            padding: '16px', background: 'var(--bg-tertiary)',
            borderRadius: 'var(--radius-md)', marginBottom: '18px'
          }}>
            <div style={{ fontWeight: '600', color: 'var(--text-primary)', marginBottom: '6px' }}>
              {resguardo.equipo.marca} {resguardo.equipo.modelo}
            </div>
            <div style={{ fontSize: '0.88rem', color: 'var(--text-secondary)', lineHeight: 1.6 }}>
              {t('inventory.serial')}: {resguardo.equipo.numero_serie || '—'}<br />
              {resguardo.accesorios && <>{t('resguardos.accesorios')}: {resguardo.accesorios}</>}
            </div>
          </div>
        )}

        {/* Condiciones completas, con scroll propio */}
        <label style={{ fontSize: '0.88rem', fontWeight: '600', color: 'var(--text-primary)', display: 'block', marginBottom: '8px' }}>
          {t('resguardos.condiciones')}
        </label>
        <div
          ref={cajaCondiciones}
          onScroll={(e) => {
            const el = e.target;
            // Se habilita la aceptación cuando llegó al final del texto.
            if (el.scrollHeight - el.scrollTop - el.clientHeight < 40) setLeyoTodo(true);
          }}
          style={{
            maxHeight: '210px', overflowY: 'auto', padding: '16px',
            background: 'var(--bg-secondary)', border: '1px solid var(--border-color)',
            borderRadius: 'var(--radius-md)', fontSize: '0.86rem', lineHeight: 1.6,
            color: 'var(--text-primary)', whiteSpace: 'pre-line', marginBottom: '8px'
          }}
        >
          {resguardo.condiciones}
        </div>

        {!leyoTodo && (
          <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '16px' }}>
            {t('resguardos.desplace_para_leer')}
          </div>
        )}

        <div className="form-group" style={{ marginTop: '16px' }}>
          <label>{t('resguardos.escriba_nombre')}</label>
          <input
            className="form-input"
            style={{ width: '100%' }}
            value={nombre}
            onChange={(e) => setNombre(e.target.value)}
            placeholder={nombreSugerido || ''}
            autoComplete="off"
          />
          <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: '6px' }}>
            {t('resguardos.nota_constancia')}
          </div>
        </div>

        <label style={{
          display: 'flex', alignItems: 'flex-start', gap: '10px',
          cursor: leyoTodo ? 'pointer' : 'not-allowed',
          opacity: leyoTodo ? 1 : 0.5, marginBottom: '20px'
        }}>
          <input
            type="checkbox"
            checked={acepto}
            disabled={!leyoTodo}
            onChange={(e) => setAcepto(e.target.checked)}
            style={{ width: '18px', height: '18px', marginTop: '2px', flexShrink: 0 }}
          />
          <span style={{ fontSize: '0.9rem', color: 'var(--text-primary)', lineHeight: 1.5 }}>
            {t('resguardos.acepto')}
          </span>
        </label>

        {error && (
          <div className="animate-scale-in" style={{
            display: 'flex', alignItems: 'center', gap: '8px',
            background: 'var(--status-espera-proveedor-bg)',
            color: 'var(--status-espera-proveedor-text)',
            padding: '12px 16px', borderRadius: 'var(--radius-md)',
            fontSize: '0.88rem', marginBottom: '16px'
          }}>
            <AlertTriangle size={16} /> {error}
          </div>
        )}

        <div style={{ display: 'flex', gap: '10px', justifyContent: 'space-between', flexWrap: 'wrap' }}>
          <button type="button" onClick={verPdf} className="btn-secondary" style={{ padding: '12px 20px' }}>
            <Download size={16} /> {t('resguardos.ver_pdf')}
          </button>
          <div style={{ display: 'flex', gap: '10px' }}>
            <button type="button" onClick={onCerrar} className="btn-secondary" style={{ padding: '12px 20px' }}>
              {t('temas.cancelar')}
            </button>
            <button type="submit" className="btn-primary" disabled={!puedeFirmar} style={{ padding: '12px 22px' }}>
              <Check size={17} />
              {enviando ? t('temas.guardando') : t('resguardos.firmar')}
            </button>
          </div>
        </div>
      </Formulario>
    </CapaModal>
  );
};

export default FirmaResguardo;
