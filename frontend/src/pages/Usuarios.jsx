import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import api from '../api/client';
import { EsqueletoLista } from '../components/Cargando';
import {
  UserPlus, Search, KeyRound, RotateCcw, FolderOpen, FileText,
  Check, X, AlertTriangle, Copy, ShieldCheck, User, Laptop, Ticket, Upload, Pencil,
  UserCheck, Lock
} from 'lucide-react';

const ESTADOS = {
  activa: ['var(--status-resuelto-text)', 'var(--status-resuelto-bg)'],
  pendiente_activacion: ['var(--status-espera-proveedor-text)', 'var(--status-espera-proveedor-bg)'],
  bloqueada: ['#D8000C', '#FFF0F0']
};

/** Panel de personas: quién existe, en qué estado y qué tiene a su cargo. */
const Usuarios = () => {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();

  const [usuarios, setUsuarios] = useState([]);
  const [cargando, setCargando] = useState(true);
  const [busqueda, setBusqueda] = useState('');
  const [filtroEstado, setFiltroEstado] = useState('');
  const [creando, setCreando] = useState(false);
  const [codigo, setCodigo] = useState(null);
  // Persona a la que se le está activando la cuenta con ella enfrente.
  const [asistida, setAsistida] = useState(null);
  const [aviso, setAviso] = useState('');

  const cargar = async () => {
    setCargando(true);
    try {
      const params = new URLSearchParams();
      if (busqueda) params.set('buscar', busqueda);
      if (filtroEstado) params.set('estado', filtroEstado);
      setUsuarios((await api.get(`/admin/usuarios?${params}`)).data);
      setAviso('');
    } catch (err) {
      setAviso(err.response?.data?.detail || t('usuarios.error_cargar'));
    } finally {
      setCargando(false);
    }
  };

  useEffect(() => {
    const temporizador = setTimeout(cargar, busqueda ? 400 : 0);
    return () => clearTimeout(temporizador);
  }, [busqueda, filtroEstado]);

  const accion = async (ruta, mensajeConfirmacion) => {
    if (mensajeConfirmacion && !window.confirm(mensajeConfirmacion)) return;
    try {
      const res = await api.post(ruta);
      setCodigo(res.data);
      cargar();
    } catch (err) {
      setAviso(err.response?.data?.detail || t('usuarios.error_accion'));
    }
  };

  const alternarActivo = async (u) => {
    try {
      await api.patch(`/admin/usuarios/${u.id}`, { activo: !u.activo });
      cargar();
    } catch (err) {
      setAviso(err.response?.data?.detail || t('usuarios.error_accion'));
    }
  };

  // Para quien no recuerda ninguna fecha y nunca va a recibir un papelito:
  // TI comprueba el gafete y le gira la pantalla para que teclee su contraseña.
  const activarEnMostrador = async (u) => {
    try {
      const res = await api.post(`/admin/usuarios/${u.id}/activacion-asistida`);
      setAsistida({ usuario: u, ...res.data });
    } catch (err) {
      setAviso(err.response?.data?.detail || t('usuarios.error_accion'));
    }
  };

  // La migración a número de empleado dejó un TMP-xxxxx en las cuentas que
  // ya existían. Nadie puede entrar con eso: hay que sustituirlo por el real.
  const corregirNumero = async (u) => {
    const nuevo = window.prompt(t('usuarios.pedir_numero', { nombre: u.nombre }), '');
    if (nuevo === null || !nuevo.trim()) return;
    try {
      await api.patch(`/admin/usuarios/${u.id}`, { numero_empleado: nuevo.trim() });
      cargar();
    } catch (err) {
      setAviso(err.response?.data?.detail || t('usuarios.error_accion'));
    }
  };

  const cambiarRol = async (u, rol) => {
    try {
      await api.patch(`/admin/usuarios/${u.id}`, { rol });
      cargar();
    } catch (err) {
      setAviso(err.response?.data?.detail || t('usuarios.error_accion'));
    }
  };

  const noAdeudo = async (u) => {
    try {
      const res = await api.get(`/expediente/${u.id}/no-adeudo`, { responseType: 'blob' });
      const url = URL.createObjectURL(res.data);
      window.open(url, '_blank', 'noopener,noreferrer');
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch {
      setAviso(t('usuarios.error_documento'));
    }
  };

  const fecha = (iso) => iso ? new Date(iso).toLocaleDateString(i18n.language, {
    day: '2-digit', month: 'short', year: 'numeric'
  }) : t('usuarios.nunca');

  return (
    <div className="page-container animate-fade-in" style={{ maxWidth: '1080px' }}>
      <h1 style={{ fontSize: '1.85rem', fontWeight: '700', marginBottom: '6px', color: 'var(--text-primary)' }}>
        {t('usuarios.title')}
      </h1>
      <p style={{ color: 'var(--text-secondary)', marginBottom: '26px' }}>
        {t('usuarios.subtitle')}
      </p>

      {aviso && (
        <div className="animate-scale-in" style={{
          display: 'flex', alignItems: 'center', gap: '10px',
          background: 'var(--status-espera-proveedor-bg)',
          color: 'var(--status-espera-proveedor-text)',
          padding: '14px 18px', borderRadius: 'var(--radius-md)',
          marginBottom: '18px', fontSize: '0.9rem'
        }}>
          <AlertTriangle size={18} /> {aviso}
        </div>
      )}

      {codigo && <TarjetaCodigo datos={codigo} onCerrar={() => setCodigo(null)} />}

      {asistida && (
        <ActivacionEnMostrador
          datos={asistida}
          onCerrar={() => setAsistida(null)}
          onListo={() => { setAsistida(null); setAviso(t('usuarios.asistida_lista')); cargar(); }}
        />
      )}

      <div style={{ display: 'flex', gap: '10px', marginBottom: '20px', flexWrap: 'wrap', alignItems: 'center' }}>
        <button onClick={() => setCreando(true)} className="btn-primary"
          style={{ padding: '10px 18px', fontSize: '0.9rem' }}>
          <UserPlus size={16} /> {t('usuarios.dar_de_alta')}
        </button>

        {/* Para 300 personas, el alta de una en una no es camino. */}
        <button onClick={() => navigate('/importar')} className="btn-secondary"
          style={{ padding: '10px 18px', fontSize: '0.9rem' }}>
          <Upload size={16} /> {t('usuarios.importar')}
        </button>

        <div style={{ position: 'relative', flex: 1, minWidth: '200px' }}>
          <Search size={16} style={{
            position: 'absolute', left: '12px', top: '50%',
            transform: 'translateY(-50%)', color: 'var(--text-muted)'
          }} />
          <input className="form-input" value={busqueda} onChange={(e) => setBusqueda(e.target.value)}
            placeholder={t('usuarios.buscar')} style={{ width: '100%', paddingLeft: '38px' }} />
        </div>

        <select className="form-select" value={filtroEstado}
          onChange={(e) => setFiltroEstado(e.target.value)} style={{ maxWidth: '220px' }}>
          <option value="">{t('usuarios.todos_estados')}</option>
          <option value="activa">{t('usuarios.estado_activa')}</option>
          <option value="pendiente_activacion">{t('usuarios.estado_pendiente_activacion')}</option>
        </select>
      </div>

      {creando && (
        <FormularioAlta
          onCerrar={() => setCreando(false)}
          onCreado={(datos) => { setCreando(false); setCodigo(datos); cargar(); }}
          onError={setAviso}
        />
      )}

      {cargando ? (
        <EsqueletoLista filas={4} />
      ) : usuarios.length === 0 ? (
        <div className="apple-card" style={{ padding: '48px', textAlign: 'center', color: 'var(--text-muted)' }}>
          {t('usuarios.sin_resultados')}
        </div>
      ) : (
        <div className="lista-escalonada" style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          {usuarios.map((u) => {
            const [color, fondo] = ESTADOS[u.estado_cuenta] || ESTADOS.bloqueada;
            const provisional = (u.numero_empleado || '').startsWith('TMP-');
            // Sin fecha registrada, esa persona depende de un código o del
            // mostrador: conviene que TI lo vea sin tener que abrir la ficha.
            const factores = u.datos_verificacion?.length || 0;
            const soloAsistida = u.estado_cuenta === 'pendiente_activacion' && factores === 0;
            // Con un solo dato, la verificación es más débil de lo que el
            // portal pretende ofrecer: conviene pedirle a RH el número de EPP.
            const unSoloFactor = u.estado_cuenta === 'pendiente_activacion' && factores === 1;
            return (
              <div key={u.id} className="apple-card" style={{
                padding: '18px 22px', display: 'flex', justifyContent: 'space-between',
                gap: '18px', flexWrap: 'wrap', opacity: u.activo ? 1 : 0.55,
                borderLeft: u.estado_cuenta === 'pendiente_activacion'
                  ? '3px solid var(--status-espera-proveedor-text)' : '3px solid transparent'
              }}>
                <div style={{ flex: 1, minWidth: '260px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '6px', flexWrap: 'wrap' }}>
                    {u.rol === 'admin'
                      ? <ShieldCheck size={16} color="var(--accent-primary)" />
                      : <User size={16} color="var(--text-secondary)" />}
                    <strong style={{ color: 'var(--text-primary)', fontSize: '0.98rem' }}>{u.nombre}</strong>
                    <span style={{
                      fontSize: '0.72rem', fontWeight: '600', padding: '3px 10px',
                      borderRadius: 'var(--radius-full)', color, background: fondo
                    }}>
                      {t(`usuarios.estado_${u.estado_cuenta}`)}
                    </span>
                    {unSoloFactor && (
                      <span title={t('usuarios.un_factor_ayuda')} style={{
                        fontSize: '0.72rem', fontWeight: '600', padding: '3px 10px',
                        borderRadius: 'var(--radius-full)',
                        color: 'var(--status-espera-proveedor-text)',
                        background: 'var(--status-espera-proveedor-bg)'
                      }}>
                        {t('usuarios.un_factor')}
                      </span>
                    )}
                    {soloAsistida && (
                      <span title={t('usuarios.solo_asistida_ayuda')} style={{
                        fontSize: '0.72rem', fontWeight: '600', padding: '3px 10px',
                        borderRadius: 'var(--radius-full)',
                        color: 'var(--text-secondary)', background: 'var(--bg-tertiary)'
                      }}>
                        {t('usuarios.solo_asistida')}
                      </span>
                    )}
                    {!u.activo && (
                      <span style={{
                        fontSize: '0.72rem', fontWeight: '600', padding: '3px 10px',
                        borderRadius: 'var(--radius-full)',
                        color: 'var(--text-secondary)', background: 'var(--bg-tertiary)'
                      }}>
                        {t('usuarios.desactivado')}
                      </span>
                    )}
                  </div>

                  <div style={{
                    fontSize: '0.86rem', color: 'var(--text-secondary)', marginBottom: '8px',
                    display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap'
                  }}>
                    {provisional ? (
                      <button onClick={() => corregirNumero(u)} style={{
                        display: 'inline-flex', alignItems: 'center', gap: '6px',
                        border: '1px dashed var(--status-espera-proveedor-text)',
                        color: 'var(--status-espera-proveedor-text)',
                        background: 'var(--status-espera-proveedor-bg)',
                        borderRadius: 'var(--radius-full)', padding: '2px 10px',
                        fontSize: '0.78rem', fontWeight: 600, cursor: 'pointer'
                      }}>
                        <Pencil size={12} /> {t('usuarios.numero_provisional')}
                      </button>
                    ) : (
                      <span>{u.numero_empleado || u.email}</span>
                    )}
                    {u.numero_empleado && u.email && <span>· {u.email}</span>}
                    {u.area ? <span>· {u.area}</span> : null}
                  </div>

                  <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap', fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                    <span style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
                      <Laptop size={13} /> {t('usuarios.equipos', { n: u.equipos_a_cargo })}
                    </span>
                    {u.resguardos_pendientes > 0 && (
                      <span style={{ display: 'flex', alignItems: 'center', gap: '5px', color: 'var(--status-espera-proveedor-text)' }}>
                        <FileText size={13} /> {t('usuarios.resguardos_pendientes', { n: u.resguardos_pendientes })}
                      </span>
                    )}
                    {u.tickets_abiertos > 0 && (
                      <span style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
                        <Ticket size={13} /> {t('usuarios.tickets_abiertos', { n: u.tickets_abiertos })}
                      </span>
                    )}
                    <span>{t('usuarios.ultimo_acceso')}: {fecha(u.ultimo_acceso)}</span>
                  </div>
                </div>

                <div style={{ display: 'flex', gap: '8px', alignItems: 'flex-start', flexWrap: 'wrap' }}>
                  <button onClick={() => navigate(`/expediente/${u.id}`)} className="btn-secondary"
                    style={{ padding: '9px 13px' }} title={t('usuarios.ver_expediente')}>
                    <FolderOpen size={15} />
                  </button>
                  <button onClick={() => noAdeudo(u)} className="btn-secondary"
                    style={{ padding: '9px 13px' }} title={t('usuarios.no_adeudo')}>
                    <FileText size={15} />
                  </button>
                  {u.estado_cuenta === 'pendiente_activacion' ? (
                    <>
                      {/* Lo que resuelve a quien no recuerda ninguna fecha:
                          se activa con la persona enfrente. Solo aparece en
                          cuentas pendientes; para una activa hay que pasar
                          antes por «Restablecer», que sí pide confirmación. */}
                      <button onClick={() => activarEnMostrador(u)} className="btn-secondary"
                        title={t('usuarios.asistida_ayuda')}
                        style={{ padding: '9px 14px', fontSize: '0.84rem' }}>
                        <UserCheck size={15} /> {t('usuarios.activar_aqui')}
                      </button>
                      <button
                        onClick={() => accion(`/admin/usuarios/${u.id}/regenerar-codigo`)}
                        className="btn-secondary" style={{ padding: '9px 14px', fontSize: '0.84rem' }}>
                        <KeyRound size={15} /> {t('usuarios.nuevo_codigo')}
                      </button>
                    </>
                  ) : (
                    <button
                      onClick={() => accion(`/admin/usuarios/${u.id}/restablecer`,
                        t('usuarios.confirmar_restablecer', { nombre: u.nombre }))}
                      className="btn-secondary" style={{ padding: '9px 14px', fontSize: '0.84rem' }}>
                      <RotateCcw size={15} /> {t('usuarios.restablecer')}
                    </button>
                  )}
                  <select className="form-select" value={u.rol}
                    onChange={(e) => cambiarRol(u, e.target.value)}
                    style={{ padding: '8px 10px', fontSize: '0.84rem', minWidth: '110px' }}>
                    <option value="usuario">{t('usuarios.rol_usuario')}</option>
                    <option value="admin">{t('usuarios.rol_admin')}</option>
                  </select>
                  <button onClick={() => alternarActivo(u)} className="btn-secondary"
                    style={{ padding: '9px 13px', color: u.activo ? '#D8000C' : 'var(--status-resuelto-text)' }}
                    title={u.activo ? t('usuarios.desactivar') : t('usuarios.reactivar')}>
                    {u.activo ? <X size={15} /> : <Check size={15} />}
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

/* ================================================================ */
const TarjetaCodigo = ({ datos, onCerrar }) => {
  const { t } = useTranslation();
  const [copiado, setCopiado] = useState(false);

  const copiar = async () => {
    try {
      await navigator.clipboard.writeText(datos.codigo);
      setCopiado(true);
      setTimeout(() => setCopiado(false), 2500);
    } catch { /* si el navegador no lo permite, el código sigue a la vista */ }
  };

  return (
    <div onClick={onCerrar} style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      padding: '20px', zIndex: 1000
    }}>
      <div onClick={(e) => e.stopPropagation()} className="apple-card animate-scale-in"
        style={{ padding: '32px', maxWidth: '480px', width: '100%', textAlign: 'center' }}>
        <KeyRound size={38} color="var(--accent-primary)" style={{ margin: '0 auto 16px' }} />
        <h2 style={{ fontSize: '1.25rem', fontWeight: '700', marginBottom: '8px', color: 'var(--text-primary)' }}>
          {t('usuarios.codigo_titulo')}
        </h2>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', marginBottom: '20px' }}>
          {datos.numero_empleado || datos.email}
        </p>

        <div style={{
          fontFamily: 'monospace', fontSize: '2rem', fontWeight: '700',
          letterSpacing: '0.16em', color: 'var(--accent-primary)',
          background: 'var(--bg-tertiary)', padding: '20px',
          borderRadius: 'var(--radius-md)', marginBottom: '14px'
        }}>
          {datos.codigo}
        </div>

        <button onClick={copiar} className="btn-secondary"
          style={{ padding: '9px 18px', fontSize: '0.86rem', marginBottom: '18px' }}>
          <Copy size={15} /> {copiado ? t('usuarios.copiado') : t('usuarios.copiar')}
        </button>

        {/* Lo importante: el código no se vuelve a mostrar. */}
        <div style={{
          background: 'var(--status-espera-proveedor-bg)',
          color: 'var(--status-espera-proveedor-text)',
          padding: '14px 16px', borderRadius: 'var(--radius-md)',
          fontSize: '0.86rem', lineHeight: 1.5, textAlign: 'left', marginBottom: '20px'
        }}>
          <strong>{t('usuarios.codigo_unica_vez')}</strong>
          <div style={{ marginTop: '6px' }}>{datos.instrucciones}</div>
        </div>

        <button onClick={onCerrar} className="btn-primary" style={{ padding: '12px 26px' }}>
          {t('usuarios.ya_lo_anote')}
        </button>
      </div>
    </div>
  );
};

/* ================================================================ */
/**
 * Activación con la persona enfrente.
 *
 * Existe porque el autoservicio no alcanza para todos: hay quien no recuerda
 * ninguna fecha y quien nunca va a recibir un papelito. TI comprueba el gafete,
 * abre esto y **le gira la pantalla**. La contraseña la teclea la persona; TI
 * no la ve ni la puede recuperar después.
 */
const ActivacionEnMostrador = ({ datos, onCerrar, onListo }) => {
  const { t } = useTranslation();
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

  const larga = password.length >= minimo;
  const coinciden = password.length > 0 && password === repetir;

  const enviar = async (e) => {
    e.preventDefault();
    if (!larga || !coinciden || enviando) return;
    setEnviando(true);
    setError('');
    try {
      // La sesión que devuelve es de la persona, no de quien está asistiendo:
      // se descarta a propósito para no sacar al admin de su sesión.
      await api.post('/auth/activar', {
        identificador: datos.numero_empleado,
        codigo: datos.codigo,
        password
      });
      onListo();
    } catch (err) {
      setError(err.response?.data?.detail || t('activar.error'));
      setEnviando(false);
    }
  };

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      padding: '20px', zIndex: 1000
    }}>
      <form onSubmit={enviar} onClick={(e) => e.stopPropagation()}
        className="apple-card animate-scale-in"
        style={{ padding: '32px', maxWidth: '460px', width: '100%' }}>
        <div style={{ textAlign: 'center', marginBottom: '18px' }}>
          <UserCheck size={34} color="var(--accent-primary)" style={{ marginBottom: '10px' }} />
          <h2 style={{ fontSize: '1.2rem', fontWeight: '700', color: 'var(--text-primary)' }}>
            {t('usuarios.asistida_titulo')}
          </h2>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', marginTop: '6px' }}>
            {datos.usuario.nombre} · {datos.usuario.numero_empleado}
          </p>
        </div>

        <div style={{
          background: 'var(--status-espera-proveedor-bg)',
          color: 'var(--status-espera-proveedor-text)',
          padding: '12px 14px', borderRadius: 'var(--radius-md)',
          fontSize: '0.86rem', lineHeight: 1.5, marginBottom: '18px'
        }}>
          <strong>{t('usuarios.asistida_entregue')}</strong>
          <div style={{ marginTop: '4px' }}>{t('usuarios.asistida_nota')}</div>
        </div>

        {error && (
          <div style={{
            background: '#FFF0F0', border: '1px solid #FFD6D6', color: '#D8000C',
            padding: '11px 13px', borderRadius: 'var(--radius-sm)',
            fontSize: '0.86rem', marginBottom: '14px'
          }}>
            {error}
          </div>
        )}

        <div className="form-group">
          <label>{t('activar.nueva_password')}</label>
          <div style={{ position: 'relative' }}>
            <Lock size={17} style={{
              position: 'absolute', left: '13px', top: '50%',
              transform: 'translateY(-50%)', color: 'var(--text-muted)'
            }} />
            <input type="password" className="form-input" required autoFocus
              style={{ width: '100%', paddingLeft: '40px' }}
              value={password} onChange={(e) => setPassword(e.target.value)} />
          </div>
          <div style={{
            fontSize: '0.8rem', marginTop: '5px',
            color: larga ? 'var(--status-resuelto-text)' : 'var(--text-muted)'
          }}>
            {t('activar.req_longitud', { n: minimo })}
          </div>
        </div>

        <div className="form-group">
          <label>{t('activar.repetir')}</label>
          <div style={{ position: 'relative' }}>
            <Lock size={17} style={{
              position: 'absolute', left: '13px', top: '50%',
              transform: 'translateY(-50%)', color: 'var(--text-muted)'
            }} />
            <input type="password" className="form-input" required
              style={{ width: '100%', paddingLeft: '40px' }}
              value={repetir} onChange={(e) => setRepetir(e.target.value)} />
          </div>
          {repetir.length > 0 && (
            <div style={{
              fontSize: '0.8rem', marginTop: '5px',
              color: coinciden ? 'var(--status-resuelto-text)' : '#D8000C'
            }}>
              {coinciden ? t('activar.req_coinciden') : t('usuarios.no_coinciden')}
            </div>
          )}
        </div>

        <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end', marginTop: '18px' }}>
          <button type="button" onClick={onCerrar} className="btn-secondary"
            style={{ padding: '10px 18px' }}>
            <X size={15} /> {t('temas.cancelar')}
          </button>
          <button type="submit" className="btn-primary"
            disabled={!larga || !coinciden || enviando} style={{ padding: '10px 18px' }}>
            <Check size={15} /> {enviando ? t('activar.activando') : t('usuarios.asistida_confirmar')}
          </button>
        </div>
      </form>
    </div>
  );
};

/* ================================================================ */
const FormularioAlta = ({ onCerrar, onCreado, onError }) => {
  const { t } = useTranslation();
  const [nombre, setNombre] = useState('');
  const [numeroEmpleado, setNumeroEmpleado] = useState('');
  const [email, setEmail] = useState('');
  const [numeroEpp, setNumeroEpp] = useState('');
  const [fechaNacimiento, setFechaNacimiento] = useState('');
  const [fechaIngreso, setFechaIngreso] = useState('');
  const [area, setArea] = useState('');
  const [rol, setRol] = useState('usuario');
  const [dominios, setDominios] = useState([]);
  const [enviando, setEnviando] = useState(false);

  useEffect(() => {
    api.get('/auth/requisitos-password')
      .then((r) => setDominios(r.data.dominios_permitidos || []))
      .catch(() => {});
  }, []);

  const enviar = async (e) => {
    e.preventDefault();
    setEnviando(true);
    try {
      const res = await api.post('/admin/usuarios', {
        nombre: nombre.trim(),
        numero_empleado: numeroEmpleado.trim(),
        // En planta mucha gente no tiene correo: se manda null, no cadena vacía.
        email: email.trim() ? email.trim().toLowerCase() : null,
        numero_epp: numeroEpp.trim() || null,
        fecha_nacimiento: fechaNacimiento || null,
        fecha_ingreso: fechaIngreso || null,
        area: area.trim() || null, rol
      });
      onCreado(res.data);
    } catch (err) {
      onError(err.response?.data?.detail || t('usuarios.error_alta'));
      setEnviando(false);
    }
  };

  return (
    <form onSubmit={enviar} className="apple-card animate-scale-in"
      style={{ padding: '26px', marginBottom: '20px', border: '1px solid var(--accent-primary)' }}>
      <h3 style={{ fontSize: '1.05rem', fontWeight: '700', marginBottom: '18px', color: 'var(--text-primary)' }}>
        {t('usuarios.alta_titulo')}
      </h3>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(230px, 1fr))', gap: '16px' }}>
        <div className="form-group">
          <label>{t('usuarios.nombre')}</label>
          <input className="form-input" required minLength={3} style={{ width: '100%' }}
            value={nombre} onChange={(e) => setNombre(e.target.value)} />
        </div>
        <div className="form-group">
          <label>{t('usuarios.numero_empleado')}</label>
          <input className="form-input" required style={{ width: '100%' }}
            autoComplete="off" placeholder={t('auth.identificador_ejemplo')}
            value={numeroEmpleado} onChange={(e) => setNumeroEmpleado(e.target.value)} />
          <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginTop: '5px' }}>
            {t('usuarios.numero_empleado_ayuda')}
          </div>
        </div>
        <div className="form-group">
          <label>{t('usuarios.email_opcional')}</label>
          <input type="email" className="form-input" style={{ width: '100%' }}
            value={email} onChange={(e) => setEmail(e.target.value)} />
          {dominios.length > 0 && (
            <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginTop: '5px' }}>
              {t('usuarios.dominios', { lista: dominios.map((d) => '@' + d).join(', ') })}
            </div>
          )}
        </div>
        <div className="form-group">
          <label>{t('usuarios.numero_epp')}</label>
          <input className="form-input" style={{ width: '100%' }}
            inputMode="numeric" maxLength={10} autoComplete="off" placeholder="0421"
            value={numeroEpp} onChange={(e) => setNumeroEpp(e.target.value)} />
          <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginTop: '5px' }}>
            {t('usuarios.numero_epp_ayuda')}
          </div>
        </div>
        <div className="form-group">
          <label>{t('usuarios.fecha_nacimiento')}</label>
          <input type="date" className="form-input" style={{ width: '100%' }}
            value={fechaNacimiento} onChange={(e) => setFechaNacimiento(e.target.value)} />
          <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginTop: '5px' }}>
            {t('usuarios.fecha_nacimiento_ayuda')}
          </div>
        </div>
        <div className="form-group">
          <label>{t('usuarios.fecha_ingreso')}</label>
          <input type="date" className="form-input" style={{ width: '100%' }}
            value={fechaIngreso} onChange={(e) => setFechaIngreso(e.target.value)} />
          <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginTop: '5px' }}>
            {t('usuarios.fecha_ingreso_ayuda')}
          </div>
        </div>
        <div className="form-group">
          <label>{t('usuarios.area')}</label>
          <input className="form-input" style={{ width: '100%' }}
            placeholder={t('usuarios.area_ejemplo')}
            value={area} onChange={(e) => setArea(e.target.value)} />
        </div>
        <div className="form-group">
          <label>{t('usuarios.rol')}</label>
          <select className="form-select" value={rol} onChange={(e) => setRol(e.target.value)}>
            <option value="usuario">{t('usuarios.rol_usuario')}</option>
            <option value="admin">{t('usuarios.rol_admin')}</option>
          </select>
        </div>
      </div>

      <div style={{
        fontSize: '0.84rem', color: 'var(--text-secondary)',
        background: 'var(--bg-tertiary)', padding: '12px 14px',
        borderRadius: 'var(--radius-md)', marginBottom: '16px', lineHeight: 1.5
      }}>
        {t('usuarios.nota_flujo')}
      </div>

      <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
        <button type="button" onClick={onCerrar} className="btn-secondary" style={{ padding: '10px 18px' }}>
          <X size={15} /> {t('temas.cancelar')}
        </button>
        <button type="submit" className="btn-primary" disabled={enviando || !nombre || !numeroEmpleado}
          style={{ padding: '10px 18px' }}>
          <Check size={15} /> {enviando ? t('temas.guardando') : t('usuarios.dar_de_alta')}
        </button>
      </div>
    </form>
  );
};

export default Usuarios;
