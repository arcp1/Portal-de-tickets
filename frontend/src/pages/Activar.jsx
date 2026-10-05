import React, { useState, useEffect } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import api from '../api/client';
import { useAuth } from '../context/AuthContext';
import LanguageSelector from '../components/LanguageSelector';
import Formulario from '../components/Formulario';
import {
  KeyRound, User, Lock, Calendar, HardHat, UserCheck,
  ArrowRight, ArrowLeft, Check, AlertTriangle
} from 'lucide-react';
import lista from '../lib/lista';

/**
 * Activación de cuenta, en tres pasos.
 *
 * **Por qué en pasos y no en un formulario.** Son 600 personas de planta
 * activándose desde el teléfono, muchas sin correo de la empresa. Una pantalla
 * con siete campos a la vez se abandona; tres pantallas de dos campos, no.
 *
 * **Por qué el paso 1 no dice si el número existe.** Es la parte contraintuitiva
 * y la que importa. Confirmar ahí que la cuenta es válida convierte la pantalla
 * en un directorio: los números van del 1 al 600, así que recorrerlos devuelve
 * quién trabaja en la planta y en qué estado está cada quien. El asistente
 * avanza siempre, y si los datos no cuadran se sabe al final, con un mensaje
 * que no distingue "no existe" de "te equivocaste". Cuesta un paso de más a
 * quien se equivocó de número; a cambio, la puerta deja de ser una lista.
 *
 * Los datos de verificación —nombre, EPP, cumpleaños— salen todos de la misma
 * lista de RH, así que como secreto valen poco. Lo que los sostiene es que esta
 * vía **solo funciona desde la red de la planta** y que se cierra tras unos
 * pocos intentos fallidos; el backend hace valer las dos cosas.
 */
const Activar = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { aplicarSesion } = useAuth();

  const [paso, setPaso] = useState(1);
  const [identificador, setIdentificador] = useState('');
  const [metodo, setMetodo] = useState('verificacion');
  const [codigo, setCodigo] = useState('');
  const [datos, setDatos] = useState({});
  const [campos, setCampos] = useState(['nombre_completo', 'numero_epp', 'fecha_nacimiento']);
  const [minimo, setMinimo] = useState(10);
  const [sugerencias, setSugerencias] = useState([]);
  const [password, setPassword] = useState('');
  const [repetir, setRepetir] = useState('');
  const [error, setError] = useState('');
  const [enviando, setEnviando] = useState(false);

  const pedirRequisitos = () =>
    api.get('/auth/requisitos-password')
      .then((r) => {
        setMinimo(r.data.longitud_minima);
        setSugerencias(lista(r.data.sugerencias, 'las sugerencias'));
      })
      .catch(() => {});

  useEffect(() => { pedirRequisitos(); }, []);

  // Paso 1 -> 2. La respuesta es la misma exista o no la cuenta, así que esto
  // nunca falla ni revela nada: solo trae qué campos pedir.
  const irAVerificacion = async (e) => {
    e.preventDefault();
    if (!identificador.trim() || enviando) return;
    setEnviando(true);
    setError('');
    try {
      const r = await api.post('/auth/estado-cuenta', { identificador: identificador.trim() });
      if (r.data.datos_verificacion?.length) setCampos(r.data.datos_verificacion);
    } catch {
      // Ni siquiera un fallo de red debe frenar aquí: se sigue con los campos
      // por omisión y la validación real ocurre al final de todos modos.
    } finally {
      setEnviando(false);
      setPaso(2);
    }
  };

  const credencialLista = metodo === 'codigo'
    ? codigo.replace(/[^A-Za-z0-9]/g, '').length >= 8
    : campos.every((c) => (datos[c] || '').trim().length > 0);

  const larga = password.length >= minimo;
  const coinciden = password.length > 0 && password === repetir;

  const activar = async (e) => {
    e.preventDefault();
    if (!larga || !coinciden || enviando) return;
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
      aplicarSesion(res.data.access_token, res.data.user);
      navigate('/', { replace: true });
    } catch (err) {
      const detalle = err.response?.data?.detail;
      // El backend responde igual para "no existe" y "datos incorrectos". Se
      // vuelve al paso 2, que es donde se corrige.
      setError(detalle || t('activar.no_cuadra'));
      setEnviando(false);
      if (err.response?.status === 400) setPaso(2);
      // Desde fuera de la planta los datos personales no bastan y el backend
      // pide el código. Antes la persona se quedaba en el paso de la
      // contraseña leyendo que le falta un código, sin el campo para ponerlo.
      if (err.response?.status === 403) {
        setMetodo('codigo');
        setPaso(2);
      }
    }
  };

  return (
    <div style={{
      minHeight: '100vh', display: 'flex', alignItems: 'center',
      justifyContent: 'center', padding: '20px', position: 'relative'
    }}>
      <div style={{ position: 'absolute', top: '24px', right: '24px' }}>
        <LanguageSelector />
      </div>

      <div className="apple-card ventana-cristal animate-scale-in" style={{
        width: '100%', maxWidth: '470px', padding: '38px 36px'
      }}>
        <Cabecera paso={paso} t={t} />

        {error && (
          <div className="animate-scale-in" style={{
            display: 'flex', alignItems: 'flex-start', gap: '10px',
            background: 'var(--peligro-bg)', color: 'var(--peligro)',
            border: '1px solid currentColor',
            padding: '12px 14px', borderRadius: 'var(--radius-sm)',
            fontSize: '0.87rem', lineHeight: 1.5, marginBottom: '18px'
          }}>
            <AlertTriangle size={17} style={{ flexShrink: 0, marginTop: '1px' }} /> {error}
          </div>
        )}

        {/* ---------- Paso 1: quién dice ser ---------- */}
        {paso === 1 && (
          <Formulario onSubmit={irAVerificacion} className="animate-appear">
            <CampoConIcono icono={<UserCheck size={18} />}>
              <input type="text" className="form-input" required autoFocus
                style={{ paddingLeft: '42px' }}
                inputMode="numeric" autoComplete="username" spellCheck={false}
                placeholder={t('auth.identificador_ejemplo')}
                value={identificador}
                onChange={(e) => setIdentificador(e.target.value)} />
            </CampoConIcono>
            {/* Sin `Pista` aquí: la cabecera ya pinta `paso1_ayuda` como
                subtítulo, así que "El que viene en su gafete. Solo dígitos."
                salía dos veces, una encima y otra debajo del mismo campo. */}

            <Boton principal disabled={!identificador.trim() || enviando}>
              {t('activar.continuar')} <ArrowRight size={18} />
            </Boton>
          </Formulario>
        )}

        {/* ---------- Paso 2: demostrar que es ---------- */}
        {paso === 2 && (
          <Formulario onSubmit={(e) => { e.preventDefault(); setError(''); setPaso(3); }}
            className="animate-appear">
            <Pestanas metodo={metodo} onCambiar={setMetodo} t={t} />

            {metodo === 'codigo' ? (
              <>
                <div className="form-group">
                  <label>{t('activar.codigo')}</label>
                  <input className="form-input" required autoFocus
                    style={{
                      fontFamily: 'var(--font-codigo)', fontSize: '1.2rem',
                      letterSpacing: '0.16em', textAlign: 'center',
                      textTransform: 'uppercase'
                    }}
                    placeholder="XXXX-XXXX" maxLength={9} autoComplete="off"
                    value={codigo} onChange={(e) => setCodigo(e.target.value.toUpperCase())} />
                  <Pista texto={t('activar.donde_codigo')} />
                </div>
              </>
            ) : (
              campos.map((campo, i) => (
                <CampoVerificacion key={campo} campo={campo} autoFocus={i === 0}
                  valor={datos[campo] || ''}
                  onCambiar={(v) => setDatos((p) => ({ ...p, [campo]: v }))} t={t} />
              ))
            )}

            <div style={{ display: 'flex', gap: '10px', marginTop: '22px' }}>
              <Boton onClick={() => { setError(''); setPaso(1); }} tipo="button">
                <ArrowLeft size={17} /> {t('activar.atras')}
              </Boton>
              <Boton principal crecer disabled={!credencialLista}>
                {t('activar.continuar')} <ArrowRight size={18} />
              </Boton>
            </div>
          </Formulario>
        )}

        {/* ---------- Paso 3: su contraseña, que nadie más verá ---------- */}
        {paso === 3 && (
          <Formulario onSubmit={activar} className="animate-appear">
            {/* Se ofrece antes de que la persona teclee, no despues de que
                falle. Pedirle a alguien de sesenta anios que invente una
                contrasena acaba siempre igual: apuntada en un papel pegado al
                monitor, y ahi ya no protege nada. */}
            {sugerencias.length > 0 && !password && (
              <div style={{
                background: 'var(--bg-secondary)', borderRadius: 'var(--radius-md)',
                padding: '16px', marginBottom: '20px'
              }}>
                <div style={{
                  fontSize: '0.87rem', fontWeight: 700,
                  color: 'var(--accent-primary)', marginBottom: '4px'
                }}>
                  {t('activar.sugerencias_titulo')}
                </div>
                <div style={{
                  fontSize: '0.79rem', color: 'var(--text-secondary)',
                  lineHeight: 1.5, marginBottom: '12px'
                }}>
                  {t('activar.sugerencias_ayuda')}
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '7px' }}>
                  {sugerencias.map((frase) => (
                    <button key={frase} type="button"
                      onClick={() => { setPassword(frase); setRepetir(frase); }}
                      style={{
                        textAlign: 'left', padding: '11px 14px', cursor: 'pointer',
                        fontFamily: 'var(--font-codigo)', fontSize: '1rem', letterSpacing: '0.01em',
                        background: 'rgba(4, 8, 16, 0.42)', color: 'var(--text-primary)',
                        border: '1px solid rgba(255,255,255,0.13)',
                        borderRadius: 'var(--radius-sm)', boxShadow: 'var(--shadow-sm)'
                      }}>
                      {frase}
                    </button>
                  ))}
                </div>

                <button type="button" onClick={pedirRequisitos} style={{
                  marginTop: '10px', background: 'none', border: 'none',
                  cursor: 'pointer', fontSize: '0.81rem', fontWeight: 600,
                  color: 'var(--accent-primary)', padding: '4px 0'
                }}>
                  {t('activar.otra_sugerencia')}
                </button>
              </div>
            )}

            <div className="form-group">
              <label>{t('activar.nueva_password')}</label>
              <CampoConIcono icono={<Lock size={18} />}>
                <input type="password" className="form-input" required autoFocus
                  style={{ paddingLeft: '42px' }} autoComplete="new-password"
                  value={password} onChange={(e) => setPassword(e.target.value)} />
              </CampoConIcono>
              <Requisito cumple={larga} texto={t('activar.req_longitud', { n: minimo })} />
            </div>

            <div className="form-group">
              <label>{t('activar.repetir')}</label>
              <CampoConIcono icono={<Lock size={18} />}>
                <input type="password" className="form-input" required
                  style={{ paddingLeft: '42px' }} autoComplete="new-password"
                  value={repetir} onChange={(e) => setRepetir(e.target.value)} />
              </CampoConIcono>
              {repetir.length > 0 && (
                <Requisito cumple={coinciden} texto={t('activar.req_coinciden')} />
              )}
            </div>

            <div style={{ display: 'flex', gap: '10px', marginTop: '22px' }}>
              <Boton onClick={() => { setError(''); setPaso(2); }} tipo="button">
                <ArrowLeft size={17} /> {t('activar.atras')}
              </Boton>
              <Boton principal crecer disabled={!larga || !coinciden || enviando}>
                <Check size={18} />
                {enviando ? t('activar.activando') : t('activar.activar')}
              </Boton>
            </div>
          </Formulario>
        )}

        <Link to="/login" style={{
          display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px',
          marginTop: '24px', fontSize: '0.87rem', color: 'var(--text-secondary)'
        }}>
          <ArrowLeft size={15} /> {t('activar.ya_tengo_cuenta')}
        </Link>
        <Link to="/terminos" className="puerta-pie-legal">
          {t('terminos.enlace')}
        </Link>
      </div>
    </div>
  );
};

/* ================================================================ */

const TITULOS = {
  1: ['activar.paso1_titulo', <UserCheck key="i" size={28} color="#ffffff" />],
  2: ['activar.paso2_titulo', <User key="i" size={28} color="#ffffff" />],
  3: ['activar.paso3_titulo', <Lock key="i" size={28} color="#ffffff" />],
};

/** Cabecera con el indicador de avance. Saber cuánto falta es lo que evita
 *  que alguien abandone a la mitad. */
const Cabecera = ({ paso, t }) => {
  const [clave, icono] = TITULOS[paso];
  return (
    <div style={{ textAlign: 'center', marginBottom: '26px' }}>
      <div className="pastilla-marca" style={{
        width: '62px', height: '62px', borderRadius: '20px',
        marginBottom: '16px'
      }}>
        {icono}
      </div>

      <div style={{
        fontSize: '0.75rem', fontWeight: 700, letterSpacing: '0.08em',
        textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: '6px'
      }}>
        {t('activar.paso', { n: paso })}
      </div>

      <h1 className="page-title" style={{ fontSize: '1.45rem', marginBottom: '8px' }}>
        {t(clave)}
      </h1>
      <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', lineHeight: 1.55 }}>
        {t(`activar.paso${paso}_ayuda`)}
      </p>

      {/* Tres segmentos: los cumplidos en azul, el actual en rosa. */}
      <div style={{ display: 'flex', gap: '6px', justifyContent: 'center', marginTop: '18px' }}>
        {[1, 2, 3].map((n) => (
          <div key={n} style={{
            height: '4px', width: n === paso ? '30px' : '18px',
            borderRadius: 'var(--radius-full)',
            // Jerarquia por luz y no por tono: el paso actual brilla, los ya
            // hechos quedan en metal apagado y los que faltan, casi apagados.
            background: n === paso ? 'var(--marca-rosa-luz)'
              : n < paso ? 'var(--marca-azul-luz)' : 'rgba(255, 255, 255, 0.16)',
            transition: 'width 0.35s var(--curva), background-color 0.35s ease'
          }} />
        ))}
      </div>
    </div>
  );
};

/* El mismo mecanismo que las pestañas de Temas y los filtros del tablero.
   Antes llevaba toda su apariencia en línea, con un velo blanco al 13% para
   la activa: ni color de marca, ni gota, ni alternancia — el último grupo del
   portal que se estilaba por su cuenta. */
const Pestanas = ({ metodo, onCambiar, t }) => (
  <div className="filtros-estado" style={{ marginBottom: '20px' }}>
    {[['verificacion', t('activar.con_verificacion')], ['codigo', t('activar.con_codigo')]]
      .map(([id, texto]) => (
        <button
          key={id}
          type="button"
          onClick={() => onCambiar(id)}
          className={`chip-filtro chip-filtro--pestana${metodo === id ? ' chip-filtro--activo' : ''}`}
          aria-pressed={metodo === id}
          style={{ flex: 1 }}
        >
          {texto}
        </button>
      ))}
  </div>
);

const CampoConIcono = ({ icono, children }) => (
  <div style={{ position: 'relative' }}>
    <span style={{
      position: 'absolute', left: '14px', top: '50%',
      transform: 'translateY(-50%)', color: 'var(--text-muted)',
      display: 'flex', pointerEvents: 'none'
    }}>
      {icono}
    </span>
    {children}
  </div>
);

const Pista = ({ texto }) => (
  <div style={{ fontSize: '0.79rem', color: 'var(--text-muted)', marginTop: '7px', lineHeight: 1.5 }}>
    {texto}
  </div>
);

const Boton = ({ principal, crecer, tipo = 'submit', onClick, disabled, children }) => (
  <button type={tipo} onClick={onClick} disabled={disabled}
    className={principal ? 'btn-primary' : 'btn-secondary'}
    style={{
      width: principal && !crecer ? '100%' : undefined,
      flex: crecer ? 1 : undefined,
      justifyContent: 'center', height: '48px', fontSize: '0.98rem',
      marginTop: principal && !crecer ? '22px' : 0
    }}>
    {children}
  </button>
);

const Requisito = ({ cumple, texto }) => (
  <div style={{
    display: 'flex', alignItems: 'center', gap: '8px',
    fontSize: '0.81rem', marginTop: '7px',
    color: cumple ? 'var(--status-resuelto-text)' : 'var(--text-muted)'
  }}>
    <Check size={14} style={{ opacity: cumple ? 1 : 0.35 }} />
    {texto}
  </div>
);

const ICONOS_CAMPO = {
  nombre_completo: User,
  numero_epp: HardHat,
  fecha_nacimiento: Calendar,
  fecha_ingreso: Calendar,
};

const CampoVerificacion = ({ campo, valor, onCambiar, autoFocus, t }) => {
  const esFecha = campo.startsWith('fecha_');
  const Icono = ICONOS_CAMPO[campo] || KeyRound;

  return (
    <div className="form-group">
      <label>{t('activar.pedir_' + campo)}</label>
      <CampoConIcono icono={<Icono size={18} />}>
        <input
          type={esFecha ? 'date' : 'text'}
          className="form-input"
          required
          autoFocus={autoFocus}
          style={{ paddingLeft: '42px' }}
          {...(campo === 'numero_epp'
            ? { inputMode: 'numeric', maxLength: 10, autoComplete: 'off',
                placeholder: t('activar.epp_ejemplo') }
            : {})}
          {...(campo === 'nombre_completo'
            ? { autoComplete: 'name', autoCapitalize: 'words' }
            : {})}
          value={valor}
          onChange={(e) => onCambiar(e.target.value)}
        />
      </CampoConIcono>
      <Pista texto={t('activar.donde_' + campo)} />
    </div>
  );
};

export default Activar;
