import React, { useState, useEffect } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import api from '../api/client';
import { useAuth } from '../context/AuthContext';
import LanguageSelector from '../components/LanguageSelector';
import {
  KeyRound, User, Lock, Calendar, HardHat, ArrowRight, ArrowLeft, Check, AlertTriangle
} from 'lucide-react';

/**
 * Activación de cuenta.
 *
 * Hay dos caminos, según cómo se dio de alta la cuenta:
 *
 *   1. Código de un solo uso, cuando TI la dio de alta una por una.
 *   2. Una fecha que la persona sabe —normalmente la de nacimiento—, para las
 *      cargas masivas de 300+ personas, donde repartir 300 códigos en papel no
 *      es realista.
 *
 * Cuál de las dos fechas se pide lo dice el backend en `dato_verificacion`: no
 * tiene caso enseñarle a alguien un campo que en su caso no sirve.
 *
 * En los dos casos la contraseña la elige la persona y TI nunca la conoce.
 */
const Activar = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { aplicarSesion } = useAuth();

  const [identificador, setIdentificador] = useState('');
  const [codigo, setCodigo] = useState('');
  // Los datos de verificación, indexados por campo: el backend dice cuáles
  // pedir y aquí se guarda lo que la persona escriba en cada uno.
  const [datos, setDatos] = useState({});
  // Qué métodos acepta esta cuenta. Se consulta al escribir el identificador.
  const [metodos, setMetodos] = useState(null);
  const [metodo, setMetodo] = useState('codigo');
  const [password, setPassword] = useState('');
  const [repetir, setRepetir] = useState('');
  const [minimo, setMinimo] = useState(10);
  const [error, setError] = useState('');
  const [enviando, setEnviando] = useState(false);

  useEffect(() => {
    api.get('/auth/requisitos-password')
      .then((r) => setMinimo(r.data.longitud_minima))
      .catch(() => {});
  }, []);

  // Al perder el foco se pregunta qué acepta esta cuenta, para no mostrarle a
  // la persona un campo que en su caso no sirve.
  const consultarMetodos = async () => {
    if (!identificador.trim()) return;
    try {
      const r = await api.post('/auth/estado-cuenta', { identificador: identificador.trim() });
      setMetodos(r.data);
      if (!r.data.acepta_codigo && r.data.acepta_verificacion) setMetodo('verificacion');
      else setMetodo('codigo');
    } catch { setMetodos(null); }
  };

  const largaSuficiente = password.length >= minimo;
  const coinciden = password.length > 0 && password === repetir;
  // Qué datos toca pedir: lo dice el backend, porque depende de lo que tenga
  // registrado esa cuenta. Sin respuesta se asume el par de la carga masiva.
  const campos = metodos?.datos_verificacion?.length
    ? metodos.datos_verificacion
    : ['numero_epp', 'fecha_nacimiento'];
  // Hay que llenarlos todos: acertar uno de dos no demuestra nada.
  const credencialLista = metodo === 'codigo'
    ? codigo.replace(/[^A-Za-z0-9]/g, '').length >= 8
    : campos.every((c) => (datos[c] || '').trim().length > 0);
  const puedeEnviar = identificador && credencialLista && largaSuficiente && coinciden && !enviando;

  const enviar = async (e) => {
    e.preventDefault();
    if (!puedeEnviar) return;
    setEnviando(true);
    setError('');
    try {
      const res = await api.post('/auth/activar', {
        identificador: identificador.trim(),
        password,
        ...(metodo === 'codigo'
          ? { codigo: codigo.trim() }
          : Object.fromEntries(campos.map((c) => [c, (datos[c] || '').trim()])))
      });
      // El backend ya devolvió sesión: no se le pide entrar otra vez.
      aplicarSesion(res.data.access_token, res.data.user);
      navigate('/', { replace: true });
    } catch (err) {
      setError(err.response?.data?.detail || t('activar.error'));
      setEnviando(false);
    }
  };

  const Pestana = ({ activa, onClick, icono, texto }) => (
    <button type="button" onClick={onClick} style={{
      flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
      gap: '6px', padding: '10px', cursor: 'pointer', fontSize: '0.85rem',
      fontWeight: activa ? 600 : 500,
      borderRadius: 'var(--radius-sm)',
      border: '1px solid ' + (activa ? 'var(--accent-primary)' : 'var(--border-color)'),
      background: activa ? 'var(--bg-tertiary)' : 'transparent',
      color: activa ? 'var(--accent-primary)' : 'var(--text-secondary)'
    }}>
      {icono} {texto}
    </button>
  );

  const Requisito = ({ cumple, texto }) => (
    <div style={{
      display: 'flex', alignItems: 'center', gap: '8px',
      fontSize: '0.82rem', marginTop: '6px',
      color: cumple ? 'var(--status-resuelto-text)' : 'var(--text-muted)'
    }}>
      <Check size={14} style={{ opacity: cumple ? 1 : 0.35 }} />
      {texto}
    </div>
  );

  return (
    <div style={{
      minHeight: '100vh', display: 'flex', alignItems: 'center',
      justifyContent: 'center', padding: '20px', position: 'relative'
    }}>
      <div style={{ position: 'absolute', top: '24px', right: '24px' }}>
        <LanguageSelector />
      </div>

      <div className="apple-card animate-scale-in" style={{
        width: '100%', maxWidth: '460px', padding: '36px', borderRadius: 'var(--radius-lg)'
      }}>
        <div style={{ textAlign: 'center', marginBottom: '28px' }}>
          <div style={{
            width: '64px', height: '64px', borderRadius: '16px',
            background: 'var(--accent-primary)', display: 'inline-flex',
            alignItems: 'center', justifyContent: 'center', marginBottom: '18px',
            boxShadow: '0 8px 16px rgba(0, 122, 255, 0.25)'
          }}>
            <KeyRound size={30} color="white" />
          </div>
          <h1 style={{ fontSize: '1.55rem', fontWeight: '700', marginBottom: '8px' }}>
            {t('activar.titulo')}
          </h1>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.92rem', lineHeight: 1.5 }}>
            {t('activar.subtitulo')}
          </p>
        </div>

        {error && (
          <div className="animate-scale-in" style={{
            display: 'flex', alignItems: 'center', gap: '10px',
            background: '#FFF0F0', border: '1px solid #FFD6D6', color: '#D8000C',
            padding: '12px 14px', borderRadius: 'var(--radius-sm)',
            fontSize: '0.88rem', marginBottom: '18px'
          }}>
            <AlertTriangle size={17} style={{ flexShrink: 0 }} /> {error}
          </div>
        )}

        <form onSubmit={enviar}>
          <div className="form-group">
            <label>{t('auth.identificador')}</label>
            <div style={{ position: 'relative' }}>
              <User size={18} style={{
                position: 'absolute', left: '14px', top: '50%',
                transform: 'translateY(-50%)', color: 'var(--text-muted)'
              }} />
              <input type="text" className="form-input" required
                style={{ width: '100%', paddingLeft: '42px' }}
                placeholder={t('auth.identificador_ejemplo')}
                autoComplete="username" autoCapitalize="off" spellCheck={false}
                value={identificador}
                onChange={(e) => setIdentificador(e.target.value)}
                onBlur={consultarMetodos} />
            </div>
          </div>

          {/* Solo se ofrece elegir cuando la cuenta admite los dos caminos. */}
          {metodos?.acepta_codigo && metodos?.acepta_verificacion && (
            <div style={{ display: 'flex', gap: '8px', marginBottom: '16px' }}>
              <Pestana activa={metodo === 'codigo'} onClick={() => setMetodo('codigo')}
                icono={<KeyRound size={15} />} texto={t('activar.con_codigo')} />
              <Pestana activa={metodo === 'verificacion'} onClick={() => setMetodo('verificacion')}
                icono={<Calendar size={15} />} texto={t('activar.con_verificacion')} />
            </div>
          )}

          {metodo === 'codigo' ? (
            <div className="form-group">
              <label>{t('activar.codigo')}</label>
              <input className="form-input" required
                style={{
                  width: '100%', fontFamily: 'monospace', fontSize: '1.15rem',
                  letterSpacing: '0.14em', textAlign: 'center', textTransform: 'uppercase'
                }}
                placeholder="XXXX-XXXX" maxLength={9} autoComplete="off"
                value={codigo} onChange={(e) => setCodigo(e.target.value.toUpperCase())} />
              <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: '6px' }}>
                {t('activar.donde_codigo')}
              </div>
            </div>
          ) : (
            campos.map((campo) => (
              <CampoVerificacion
                key={campo}
                campo={campo}
                valor={datos[campo] || ''}
                onCambiar={(v) => setDatos((previo) => ({ ...previo, [campo]: v }))}
                t={t}
              />
            ))
          )}

          <div className="form-group">
            <label>{t('activar.nueva_password')}</label>
            <div style={{ position: 'relative' }}>
              <Lock size={18} style={{
                position: 'absolute', left: '14px', top: '50%',
                transform: 'translateY(-50%)', color: 'var(--text-muted)'
              }} />
              <input type="password" className="form-input" required
                style={{ width: '100%', paddingLeft: '42px' }}
                value={password} onChange={(e) => setPassword(e.target.value)} />
            </div>
            <Requisito cumple={largaSuficiente} texto={t('activar.req_longitud', { n: minimo })} />
          </div>

          <div className="form-group">
            <label>{t('activar.repetir')}</label>
            <div style={{ position: 'relative' }}>
              <Lock size={18} style={{
                position: 'absolute', left: '14px', top: '50%',
                transform: 'translateY(-50%)', color: 'var(--text-muted)'
              }} />
              <input type="password" className="form-input" required
                style={{ width: '100%', paddingLeft: '42px' }}
                value={repetir} onChange={(e) => setRepetir(e.target.value)} />
            </div>
            {repetir.length > 0 && (
              <Requisito cumple={coinciden} texto={t('activar.req_coinciden')} />
            )}
          </div>

          <button type="submit" className="btn-primary" disabled={!puedeEnviar}
            style={{ width: '100%', justifyContent: 'center', marginTop: '22px', height: '48px', fontSize: '1rem' }}>
            {enviando ? t('activar.activando') : (
              <>{t('activar.activar')} <ArrowRight size={18} /></>
            )}
          </button>
        </form>

        <Link to="/login" style={{
          display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px',
          marginTop: '22px', fontSize: '0.88rem', color: 'var(--text-secondary)',
          textDecoration: 'none'
        }}>
          <ArrowLeft size={15} /> {t('activar.ya_tengo_cuenta')}
        </Link>
      </div>
    </div>
  );
};

/**
 * Un dato de verificación. El número de EPP es texto corto de dígitos; las
 * fechas van con selector de calendario.
 */
const CampoVerificacion = ({ campo, valor, onCambiar, t }) => {
  const esFecha = campo.startsWith('fecha_');
  const Icono = esFecha ? Calendar : HardHat;

  return (
    <div className="form-group">
      <label>{t('activar.pedir_' + campo)}</label>
      <div style={{ position: 'relative' }}>
        <Icono size={18} style={{
          position: 'absolute', left: '14px', top: '50%',
          transform: 'translateY(-50%)', color: 'var(--text-muted)'
        }} />
        <input
          type={esFecha ? 'date' : 'text'}
          className="form-input"
          required
          style={{ width: '100%', paddingLeft: '42px' }}
          {...(esFecha ? {} : {
            inputMode: 'numeric',
            maxLength: 10,
            autoComplete: 'off',
            placeholder: t('activar.epp_ejemplo')
          })}
          value={valor}
          onChange={(e) => onCambiar(e.target.value)}
        />
      </div>
      <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: '6px' }}>
        {t('activar.donde_' + campo)}
      </div>
    </div>
  );
};

export default Activar;
