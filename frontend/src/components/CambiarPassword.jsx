import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { KeyRound, AlertTriangle, Check, X, Sparkles } from 'lucide-react';
import api from '../api/client';
import CapaModal from './CapaModal';

/**
 * Cambiar la propia contraseña, sin pasar por TI.
 *
 * **Por qué existe.** El endpoint `/auth/cambiar-password` estaba construido
 * desde el principio y no había forma de llegar a él: ni pantalla, ni menú,
 * ni un texto traducido. Quien sospechaba que le habían visto la contraseña
 * solo podía pedirle a TI que le restableciera la cuenta —lo que borra la
 * contraseña y le manda de vuelta al alta con un código—, o quedarse como
 * estaba. Eso dejaba coja la promesa que hace la pantalla de activación:
 * «Solo usted la va a conocer. Ni el área de TI puede verla».
 *
 * **La sesión se cae al cambiarla, y eso está bien.** El backend sube la
 * versión del token, así que cualquier sesión abierta con la contraseña
 * anterior deja de valer —incluida esta—. Es justo lo que uno quiere cuando
 * la cambia porque cree que se la vieron. Como el efecto sorprende, se avisa
 * antes de empezar y se acompaña a la puerta después, en vez de dejar que la
 * siguiente petición devuelva un 401 y el portal salte al login sin explicar
 * nada.
 *
 * **Las sugerencias las da el servidor.** Mismo criterio que en el alta: tres
 * frases ya listas, generadas con el generador criptográfico del backend y no
 * con el del navegador. Aquí importa más todavía, porque a quien cambia su
 * contraseña por segunda vez se le acaban antes las ideas.
 */
export default function CambiarPassword({ onCerrar, onCambiada }) {
  const { t } = useTranslation();

  const [actual, setActual] = useState('');
  const [nueva, setNueva] = useState('');
  const [repetida, setRepetida] = useState('');
  const [requisitos, setRequisitos] = useState(null);
  const [error, setError] = useState('');
  const [enviando, setEnviando] = useState(false);
  const [lista, setLista] = useState(false);

  useEffect(() => {
    api.get('/auth/requisitos-password')
      .then((r) => setRequisitos(r.data))
      // Sin requisitos se puede cambiar igual: el servidor los aplica de
      // todas formas y responde con el motivo si algo no cuadra.
      .catch(() => setRequisitos(null));
  }, []);

  const minimo = requisitos?.longitud_minima ?? 10;
  const cortita = nueva.length > 0 && nueva.length < minimo;
  const noCoinciden = repetida.length > 0 && nueva !== repetida;
  const puedeEnviar = actual && nueva.length >= minimo && nueva === repetida && !enviando;

  const enviar = async (e) => {
    e.preventDefault();
    if (!puedeEnviar) return;
    setError('');
    setEnviando(true);
    try {
      await api.post('/auth/cambiar-password', {
        password_actual: actual,
        password_nueva: nueva,
      });
      setLista(true);
    } catch (err) {
      // El servidor explica el motivo concreto —la vigente no es correcta, la
      // nueva es muy corta, es la misma de antes, se parece a sus datos—; el
      // texto de reserva solo entra si no hubo respuesta.
      const detalle = err.response?.data?.detail;
      setError(typeof detalle === 'string' && detalle ? detalle : t('password.error_generico'));
      setEnviando(false);
    }
  };

  if (lista) {
    return (
      <CapaModal etiqueta={t('password.titulo')}>
        <div className="apple-card ventana-cristal animate-scale-in"
          style={{ width: '100%', maxWidth: '440px', padding: '32px 30px', textAlign: 'center' }}>
          <div className="pastilla-marca" style={{
            width: '54px', height: '54px', borderRadius: '17px', margin: '0 auto 16px'
          }}>
            <Check size={26} color="#ffffff" />
          </div>
          <h2 className="page-title" style={{ fontSize: '1.3rem', marginBottom: '10px' }}>
            {t('password.lista_titulo')}
          </h2>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.92rem', lineHeight: 1.55, marginBottom: '22px' }}>
            {t('password.lista_detalle')}
          </p>
          <button onClick={onCambiada} className="btn-primary" style={{ width: '100%', padding: '12px' }}>
            {t('password.ir_al_login')}
          </button>
        </div>
      </CapaModal>
    );
  }

  return (
    <CapaModal onCerrar={enviando ? undefined : onCerrar} etiqueta={t('password.titulo')}>
      <form
        onSubmit={enviar}
        onClick={(e) => e.stopPropagation()}
        className="apple-card ventana-cristal animate-scale-in"
        style={{ width: '100%', maxWidth: '460px', padding: '28px 30px' }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '11px', marginBottom: '6px' }}>
          <KeyRound size={19} style={{ color: 'var(--accent-primary)', flexShrink: 0 }} />
          <h2 className="page-title" style={{ fontSize: '1.22rem', margin: 0 }}>
            {t('password.titulo')}
          </h2>
        </div>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.87rem', lineHeight: 1.55, marginBottom: '20px' }}>
          {t('password.aviso_sesion')}
        </p>

        {error && (
          <div className="animate-scale-in" style={{
            display: 'flex', alignItems: 'flex-start', gap: '10px',
            background: 'var(--peligro-bg)', color: 'var(--peligro)',
            border: '1px solid currentColor', padding: '11px 13px',
            borderRadius: 'var(--radius-sm)', fontSize: '0.86rem',
            lineHeight: 1.5, marginBottom: '16px'
          }}>
            <AlertTriangle size={16} style={{ flexShrink: 0, marginTop: '2px' }} /> {error}
          </div>
        )}

        <div className="form-group">
          <label htmlFor="pwd-actual">{t('password.actual')}</label>
          <input id="pwd-actual" type="password" className="form-input" required autoFocus
            autoComplete="current-password" value={actual}
            onChange={(e) => setActual(e.target.value)} />
        </div>

        <div className="form-group" style={{ marginBottom: '4px' }}>
          <label htmlFor="pwd-nueva">{t('password.nueva')}</label>
          <input id="pwd-nueva" type="password" className="form-input" required
            autoComplete="new-password" value={nueva}
            onChange={(e) => setNueva(e.target.value)} />
        </div>
        <div style={{
          fontSize: '0.78rem', lineHeight: 1.5, marginBottom: '14px',
          color: cortita ? 'var(--status-espera-proveedor-text)' : 'var(--text-muted)'
        }}>
          {t('password.minimo', { n: minimo })}
        </div>

        <div className="form-group" style={{ marginBottom: '4px' }}>
          <label htmlFor="pwd-repetir">{t('password.repetir')}</label>
          <input id="pwd-repetir" type="password" className="form-input" required
            autoComplete="new-password" value={repetida}
            onChange={(e) => setRepetida(e.target.value)} />
        </div>
        <div style={{
          fontSize: '0.78rem', lineHeight: 1.5, minHeight: '18px', marginBottom: '16px',
          color: noCoinciden ? 'var(--peligro)' : 'var(--text-muted)'
        }}>
          {noCoinciden ? t('password.no_coinciden') : ''}
        </div>

        {/* Tres frases ya hechas. Pedirle a alguien que invente una contraseña
            de diez caracteres termina siempre igual: apuntada en un papel. */}
        {requisitos?.sugerencias?.length > 0 && (
          <div style={{
            background: 'var(--bg-tertiary)', borderRadius: 'var(--radius-sm)',
            padding: '12px 14px', marginBottom: '20px'
          }}>
            <div style={{
              display: 'flex', alignItems: 'center', gap: '7px',
              fontSize: '0.78rem', fontWeight: 600,
              color: 'var(--accent-primary)', marginBottom: '9px'
            }}>
              <Sparkles size={14} /> {t('password.sugerencias')}
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '7px' }}>
              {requisitos.sugerencias.map((frase) => (
                <button key={frase} type="button"
                  onClick={() => { setNueva(frase); setRepetida(frase); }}
                  className="btn-secondary"
                  style={{ padding: '5px 11px', fontSize: '0.8rem', fontFamily: 'var(--font-codigo)' }}>
                  {frase}
                </button>
              ))}
            </div>
          </div>
        )}

        <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
          <button type="button" onClick={onCerrar} className="btn-secondary"
            disabled={enviando} style={{ padding: '10px 18px' }}>
            <X size={15} /> {t('comun.cancelar')}
          </button>
          <button type="submit" className="btn-primary"
            disabled={!puedeEnviar} style={{ padding: '10px 20px' }}>
            <Check size={15} /> {enviando ? t('password.cambiando') : t('password.confirmar')}
          </button>
        </div>
      </form>
    </CapaModal>
  );
}
