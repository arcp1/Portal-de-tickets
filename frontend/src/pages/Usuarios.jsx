import React, { useState, useEffect, useRef } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import api from '../api/client';
import { EsqueletoLista } from '../components/Cargando';
import {
  UserPlus, Search, KeyRound, RotateCcw, FolderOpen, FileText,
  Check, X, AlertTriangle, Copy, ShieldCheck, User, Laptop, Ticket, Upload, Pencil,
  UserCheck, Lock, Trash2, UserX
} from 'lucide-react';
import CapaModal from '../components/CapaModal';
import Confirmacion from '../components/Confirmacion';
import { useAuth } from '../context/AuthContext';
import Selector from '../components/Selector';
import Formulario from '../components/Formulario';
import Aviso from '../components/Aviso';
import { copiarTexto, seleccionarContenido } from '../lib/portapapeles';
import lista from '../lib/lista';
import { avisar } from '../lib/avisos';
import { usePlantas, EtiquetaPlanta, PlantasMultiples, SelectorPlanta } from '../lib/plantas';

const ESTADOS = {
  activa: ['var(--status-resuelto-text)', 'var(--status-resuelto-bg)'],
  pendiente_activacion: ['var(--status-espera-proveedor-text)', 'var(--status-espera-proveedor-bg)'],
  bloqueada: ['var(--peligro)', 'var(--peligro-bg)']
};

/** Panel de personas: quién existe, en qué estado y qué tiene a su cargo. */
const Usuarios = () => {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  // Para no ofrecerle al admin acciones sobre su propia ficha que el backend
  // rechaza de plano (ver `editar` en app/api/cuentas.py).
  const { user: sesion } = useAuth();

  const [usuarios, setUsuarios] = useState([]);
  const [cargando, setCargando] = useState(true);
  const [busqueda, setBusqueda] = useState('');
  const [filtroEstado, setFiltroEstado] = useState('');
  const [creando, setCreando] = useState(false);
  const [codigo, setCodigo] = useState(null);
  // Persona a la que se le está activando la cuenta con ella enfrente.
  const [asistida, setAsistida] = useState(null);
  const [aviso, setAviso] = useState('');
  // Lo que está esperando una respuesta del admin. Cada uno guarda lo justo
  // para poder rematar la operación cuando confirme: null = nada abierto.
  const [porRestablecer, setPorRestablecer] = useState(null);
  const [porRenumerar, setPorRenumerar] = useState(null);
  // Sobre quién está abierto el diálogo de baja/eliminación.
  const [porQuitar, setPorQuitar] = useState(null);
  const [porReactivar, setPorReactivar] = useState(null);
  // Multi-planta: a quién se le están cambiando las plantas (y, si viene de
  // quitarle el rol de TI, el rol que espera a que se elijan).
  const [plantas] = usePlantas();
  const variasPlantas = plantas.length > 1;
  const [filtroPlanta, setFiltroPlanta] = useState(null);
  const [porPlantas, setPorPlantas] = useState(null);

  const cargar = async () => {
    setCargando(true);
    try {
      const params = new URLSearchParams();
      if (busqueda) params.set('buscar', busqueda);
      if (filtroEstado) params.set('estado', filtroEstado);
      if (filtroPlanta) params.set('sitio_id', String(filtroPlanta));
      setUsuarios(lista((await api.get(`/admin/usuarios?${params}`)).data, 'los usuarios'));
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
  }, [busqueda, filtroEstado, filtroPlanta]);

  // **Una a la vez.** Estas acciones generan un código y cada una anula el
  // anterior: con un doble clic salían dos, y el diálogo enseñaba el de la
  // respuesta que llegara al último, que podía ser justo el ya anulado. TI
  // entregaba un código que no servía.
  const accionEnCurso = useRef(false);
  const accion = async (ruta) => {
    if (accionEnCurso.current) return;
    accionEnCurso.current = true;
    try {
      const res = await api.post(ruta);
      setCodigo(res.data);
      cargar();
    } catch (err) {
      setAviso(err.response?.data?.detail || t('usuarios.error_accion'));
    } finally {
      accionEnCurso.current = false;
    }
  };

  const alternarActivo = async (u, activo) => {
    try {
      await api.patch(`/admin/usuarios/${u.id}`, { activo });
      cargar();
    } catch (err) {
      setAviso(err.response?.data?.detail || t('usuarios.error_accion'));
    }
  };

  /* **Eliminar no es desactivar más fuerte.** La baja corta el acceso y se
     deshace; esto saca a la persona del padrón y no tiene vuelta. Lo que dejó
     hecho —tickets, comentarios, resguardos, documentos— se queda con su
     nombre; lo que se borra es lo que la identifica y lo que la dejaba entrar.
     El backend lo explica con detalle en `eliminar` (app/api/cuentas.py). */
  const eliminar = async (u) => {
    try {
      await api.delete(`/admin/usuarios/${u.id}`);
      setAviso('');
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
  const corregirNumero = async (u, nuevo) => {
    setPorRenumerar(null);
    try {
      await api.patch(`/admin/usuarios/${u.id}`, { numero_empleado: nuevo });
      cargar();
    } catch (err) {
      setAviso(err.response?.data?.detail || t('usuarios.error_accion'));
    }
  };

  /* La sanción por pedir prioridad alta sin motivo, y su vuelta atrás. Sin
     confirmación a propósito: se deshace con el mismo clic y queda en la
     bitácora. Sí se dice qué pasó, porque una casilla que cambia sola en una
     lista larga no se nota. */
  const cambiarPrioridadAlta = async (u, permitida) => {
    try {
      await api.patch(`/admin/usuarios/${u.id}`, { puede_usar_prioridad_alta: permitida });
      avisar(t(permitida ? 'usuarios.prioridad_alta_devuelta' : 'usuarios.prioridad_alta_revocada',
        { nombre: u.nombre }), { tono: 'exito' });
      cargar();
    } catch (err) {
      setAviso(err.response?.data?.detail || t('usuarios.error_accion'));
    }
  };

  const cambiarRol = async (u, rol) => {
    // Al dejar de ser TI, la persona necesita al menos una planta: con varias,
    // se le pregunta a quien administra en vez de adivinar.
    if (rol === 'usuario' && u.rol === 'admin' && variasPlantas) {
      setPorPlantas({ usuario: u, rol });
      return;
    }
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
    <div className="page-container animate-fade-in">
      <div className="page-header">
        <div>
          <h1 className="page-title">
            {t('usuarios.title')}
          </h1>
          <p>
              {t('usuarios.subtitle')}
          </p>
        </div>
      </div>

      <Aviso texto={aviso} />

      {codigo && <TarjetaCodigo datos={codigo} onCerrar={() => setCodigo(null)} />}

      {asistida && (
        <ActivacionEnMostrador
          datos={asistida}
          onCerrar={() => setAsistida(null)}
          onListo={() => { setAsistida(null); setAviso(t('usuarios.asistida_lista')); cargar(); }}
        />
      )}

      <div className="barra-herramientas">
        <button onClick={() => setCreando(true)} className="btn-acento"
          style={{ padding: '10px 18px', fontSize: '0.9rem' }}>
          <UserPlus size={16} /> {t('usuarios.dar_de_alta')}
        </button>

        {/* Para 300 personas, el alta de una en una no es camino. */}
        <button onClick={() => navigate('/personas/importar')} className="btn-secondary"
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

        {/* **«Dados de baja» es la única forma de verlos.** Antes salían
            mezclados con el resto del padrón, con un distintivo rojo y algo de
            transparencia: una lista que crecía con gente a la que ya no se le
            puede hacer nada. El desplegable manda sobre la lista, así que es
            donde toca ponerlo; el backend hace lo propio y no los devuelve si
            no se piden (ver `listar` en app/api/cuentas.py). */}
        <Selector className="form-select" value={filtroEstado}
          onChange={(e) => setFiltroEstado(e.target.value)} style={{ maxWidth: '220px' }}>
          <option value="">{t('usuarios.todos_estados')}</option>
          <option value="activa">{t('usuarios.estado_activa')}</option>
          <option value="pendiente_activacion">{t('usuarios.estado_pendiente_activacion')}</option>
          <option value="baja">{t('usuarios.estado_baja')}</option>
        </Selector>
        {variasPlantas && (
          <SelectorPlanta todas plantas={plantas} value={filtroPlanta} onChange={setFiltroPlanta}
            style={{ maxWidth: '240px' }} />
        )}
      </div>

      {porPlantas && (
        <DialogoPlantas
          usuario={porPlantas.usuario}
          rol={porPlantas.rol}
          plantas={plantas}
          onCerrar={() => setPorPlantas(null)}
          onGuardado={() => { setPorPlantas(null); cargar(); }}
        />
      )}

      {porRestablecer && (
        <Confirmacion
          titulo={t('usuarios.restablecer')}
          mensaje={t('usuarios.confirmar_restablecer', { nombre: porRestablecer.nombre })}
          textoConfirmar={t('usuarios.restablecer')}
          tono="peligro"
          onConfirmar={() => {
            const u = porRestablecer;
            setPorRestablecer(null);
            accion(`/admin/usuarios/${u.id}/restablecer`);
          }}
          onCancelar={() => setPorRestablecer(null)}
        />
      )}

      {porQuitar && (
        <DialogoQuitar
          usuario={porQuitar}
          onCerrar={() => setPorQuitar(null)}
          onBaja={() => { const u = porQuitar; setPorQuitar(null); alternarActivo(u, false); }}
          onEliminar={() => { const u = porQuitar; setPorQuitar(null); eliminar(u); }}
        />
      )}

      {porReactivar && (
        <Confirmacion
          titulo={t('usuarios.reactivar')}
          mensaje={t('usuarios.confirmar_reactivar', { nombre: porReactivar.nombre })}
          textoConfirmar={t('usuarios.reactivar')}
          onConfirmar={() => {
            const u = porReactivar;
            setPorReactivar(null);
            alternarActivo(u, true);
          }}
          onCancelar={() => setPorReactivar(null)}
        />
      )}

      {porRenumerar && (
        <Confirmacion
          titulo={t('usuarios.numero_empleado')}
          /* Un TMP- se sustituye desde cero; un número mal tecleado se corrige
             partiendo de lo que hay, que casi siempre es un dígito. */
          mensaje={(porRenumerar.numero_empleado || '').startsWith('TMP-')
            ? t('usuarios.numero_empleado_ayuda')
            : t('usuarios.corregir_numero_ayuda')}
          textoConfirmar={t('temas.guardar')}
          campo={{
            etiqueta: t('usuarios.pedir_numero', { nombre: porRenumerar.nombre }),
            valorInicial: (porRenumerar.numero_empleado || '').startsWith('TMP-')
              ? '' : porRenumerar.numero_empleado,
          }}
          onConfirmar={(valor) => corregirNumero(porRenumerar, valor)}
          onCancelar={() => setPorRenumerar(null)}
        />
      )}

      {creando && (
        <FormularioAlta
          onCerrar={() => setCreando(false)}
          onCreado={(datos) => { setCreando(false); setCodigo(datos); cargar(); }}
          onError={setAviso}
        />
      )}

      {/* Que la lista esté enseñando algo distinto de lo normal se dice, no
          se deduce: quien llega aquí desde el desplegable ve nombres con
          distintivo rojo y conviene que sepa por qué están todos así. */}
      {filtroEstado === 'baja' && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '14px',
          padding: '11px 15px', borderRadius: 'var(--radius-md)',
          background: 'var(--bg-tertiary)', color: 'var(--text-secondary)',
          fontSize: '0.85rem', lineHeight: 1.45
        }}>
          <UserX size={16} style={{ flexShrink: 0 }} />
          {t('usuarios.solo_bajas_nota')}
        </div>
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
            //
            // Los dos avisos hablan de cómo se va a activar la cuenta, así que
            // sobre una baja no dicen nada: esa persona no se va a activar
            // hasta que alguien le devuelva el acceso, y entonces vuelven.
            const soloAsistida = u.activo && u.estado_cuenta === 'pendiente_activacion' && factores === 0;
            // Con un solo dato, la verificación es más débil de lo que el
            // portal pretende ofrecer: conviene pedirle a RH el número de EPP.
            const unSoloFactor = u.activo && u.estado_cuenta === 'pendiente_activacion' && factores === 1;
            return (
              /* **La fila de un dado de baja ya no se atenúa.**

                 El 55 % de opacidad servía cuando salían mezclados entre los
                 activos: era la forma de que la lista dijera de un vistazo
                 quién no entra. Ahora viven bajo su propio filtro, así que
                 aplicarlo tiñe la pantalla entera —nombres, botones,
                 desplegables— y deja el texto por debajo del contraste
                 legible justo cuando se ha entrado ahí a propósito para
                 trabajar con ellos. Quien no tiene acceso se distingue por su
                 distintivo, que es texto y se lee. */
              <div key={u.id} className="apple-card" style={{
                padding: '18px 22px', display: 'flex', justifyContent: 'space-between',
                gap: '18px', flexWrap: 'wrap',
                borderLeft: u.estado_cuenta === 'pendiente_activacion' && u.activo
                  ? '3px solid var(--status-espera-proveedor-text)' : '3px solid transparent'
              }}>
                <div style={{ flex: 1, minWidth: '260px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '6px', flexWrap: 'wrap' }}>
                    {u.rol === 'admin'
                      ? <ShieldCheck size={16} color="var(--accent-primary)" />
                      : <User size={16} color="var(--text-secondary)" />}
                    <strong style={{ color: 'var(--text-primary)', fontSize: '0.98rem' }}>{u.nombre}</strong>
                    {/* TI es global; una persona de planta, en las suyas. */}
                    {u.rol === 'admin' ? (
                      <span className="chip-dato chip-planta" title={t('plantas.ti_global_ayuda')}>
                        {t('plantas.ti_global')}
                      </span>
                    ) : (
                      /* **El chip de la planta es el botón para cambiarla.**
                         Antes el lápiz solo aparecía con dos plantas o más, así
                         que con una sola no había nada que pulsar y parecía
                         que la asignación no existía. Ahora está siempre: el
                         diálogo dice qué hacer cuando solo hay una. A una
                         baja no se le ofrece, como el rol: decide qué ve al
                         entrar, y no entra. */
                      u.activo && u.id !== sesion?.id ? (
                        <button type="button" className="plantas-boton"
                          onClick={() => setPorPlantas({ usuario: u, rol: null })}
                          title={t('plantas.cambiar')} aria-label={t('plantas.cambiar')}>
                          {(u.plantas || []).map((pl) => <EtiquetaPlanta key={pl.id} planta={pl} compacta />)}
                          <span className="plantas-boton-lapiz"><Pencil size={12} /></span>
                        </button>
                      ) : (
                        (u.plantas || []).map((pl) => <EtiquetaPlanta key={pl.id} planta={pl} compacta />)
                      )
                    )}
                    {/* **Una sola insignia de estado.** Antes se pintaban las
                        dos: `estado_cuenta` seguía diciendo "Activa" —porque
                        esa columna habla de si la cuenta está activada, no de
                        si tiene acceso— y al lado aparecía "Desactivado". La
                        fila se contradecía a sí misma. Manda lo que decide si
                        la persona puede entrar hoy; el otro dato no le sirve a
                        nadie mientras la cuenta esté cerrada. */}
                    {u.activo ? (
                      <span className="chip-dato" style={{ color, background: fondo }}>
                        {t(`usuarios.estado_${u.estado_cuenta}`)}
                      </span>
                    ) : (
                      <span className="chip-dato" style={{ color: 'var(--peligro)', background: 'var(--peligro-bg)' }}>
                        {t('usuarios.desactivado')}
                      </span>
                    )}
                    {unSoloFactor && (
                      <span title={t('usuarios.un_factor_ayuda')} className="chip-dato" style={{ color: 'var(--status-espera-proveedor-text)', background: 'var(--status-espera-proveedor-bg)' }}>
                        {t('usuarios.un_factor')}
                      </span>
                    )}
                    {soloAsistida && (
                      <span title={t('usuarios.solo_asistida_ayuda')} className="chip-dato" style={{ color: 'var(--text-secondary)', background: 'var(--bg-tertiary)' }}>
                        {t('usuarios.solo_asistida')}
                      </span>
                    )}
                    {/* Una sanción vigente tiene que verse sin abrir nada:
                        es lo primero que hay que saber al revisar si ya se
                        puede devolver. */}
                    {u.rol !== 'admin' && u.puede_usar_prioridad_alta === false && (
                      <span title={t('usuarios.sin_prioridad_alta_ayuda')} className="chip-dato" style={{ color: 'var(--peligro)', background: 'var(--peligro-bg)' }}>
                        {t('usuarios.sin_prioridad_alta')}
                      </span>
                    )}
                  </div>

                  <div style={{
                    fontSize: '0.86rem', color: 'var(--text-secondary)', marginBottom: '8px',
                    display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap'
                  }}>
                    {provisional ? (
                      <button onClick={() => setPorRenumerar(u)} style={{
                        display: 'inline-flex', alignItems: 'center', gap: '6px',
                        border: '1px dashed var(--status-espera-proveedor-text)',
                        color: 'var(--status-espera-proveedor-text)',
                        background: 'var(--status-espera-proveedor-bg)',
                        borderRadius: 'var(--radius-full)', padding: '2px 10px',
                        fontSize: '0.78rem', fontWeight: 600, cursor: 'pointer'
                      }}>
                        <Pencil size={12} /> {t('usuarios.numero_provisional')}
                      </button>
                    ) : u.activo && u.estado_cuenta === 'pendiente_activacion' && u.numero_empleado ? (
                      /* Mientras no se active, el número es solo un dato del
                         alta y se corrige aquí; ya activa, entra con él y el
                         backend no deja cambiarlo. */
                      <button onClick={() => setPorRenumerar(u)} title={t('usuarios.corregir_numero')}
                        aria-label={t('usuarios.corregir_numero')}
                        style={{
                          display: 'inline-flex', alignItems: 'center', gap: '5px',
                          border: '1px dashed var(--border-color)', background: 'transparent',
                          color: 'inherit', borderRadius: 'var(--radius-full)', padding: '1px 8px',
                          font: 'inherit', cursor: 'pointer'
                        }}>
                        {u.numero_empleado} <Pencil size={11} />
                      </button>
                    ) : (
                      <span>{u.numero_empleado || u.email}</span>
                    )}
                    {u.numero_empleado && u.email && <span>· {u.email}</span>}
                    {u.area ? <span>· {u.area}</span> : null}
                  </div>

                  <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap', fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                    {/* Como los otros dos: solo si hay algo que contar. Un
                        «0 equipos» repetido en cada fila no informa de nada y
                        empuja al dato que sí importa —el último acceso— fuera
                        del golpe de vista. */}
                    {u.equipos_a_cargo > 0 && (
                      <span style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
                        <Laptop size={13} /> {t('usuarios.equipos', { count: u.equipos_a_cargo })}
                      </span>
                    )}
                    {u.resguardos_pendientes > 0 && (
                      <span style={{ display: 'flex', alignItems: 'center', gap: '5px', color: 'var(--status-espera-proveedor-text)' }}>
                        <FileText size={13} /> {t('usuarios.resguardos_pendientes', { n: u.resguardos_pendientes })}
                      </span>
                    )}
                    {u.tickets_abiertos > 0 && (
                      <span style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
                        <Ticket size={13} /> {t('usuarios.tickets_abiertos', { count: u.tickets_abiertos })}
                      </span>
                    )}
                    <span>{t('usuarios.ultimo_acceso')}: {fecha(u.ultimo_acceso)}</span>
                  </div>
                </div>

                <div style={{ display: 'flex', gap: '8px', alignItems: 'flex-start', flexWrap: 'wrap' }}>
                  <button onClick={() => navigate(`/personas/${u.id}`)} className="btn-secondary"
                    style={{ padding: '9px 13px' }} title={t('usuarios.ver_expediente')}>
                    <FolderOpen size={15} />
                  </button>
                  <button onClick={() => noAdeudo(u)} className="btn-secondary"
                    style={{ padding: '9px 13px' }} title={t('usuarios.no_adeudo')}>
                    <FileText size={15} />
                  </button>
                  {/* **A quien no tiene acceso no se le ofrece nada que
                      dependa de tenerlo.**

                      La lista de bajas enseñaba «Restablecer», «Activar aquí»
                      y «Nuevo código» sobre gente que no puede entrar: los
                      tres montan una contraseña o un código que no sirve para
                      nada mientras la cuenta esté cerrada. Un botón que
                      completa su trabajo y no cambia nada es peor que uno que
                      falla, porque nadie se entera.

                      Lo que sí tiene sentido sobre una baja son las cuatro
                      cosas que quedan: mirar su expediente, sacarle la carta
                      de no adeudo, devolverle la entrada o eliminarla. Al
                      reactivarla vuelven las demás. */}
                  {u.activo && (u.estado_cuenta === 'pendiente_activacion' ? (
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
                  ) : u.id !== sesion?.id && (
                    /* Tampoco sobre la propia ficha: anula la contraseña y
                       cierra la sesión de quien lo pulsa. Para eso está
                       «Cambiar mi contraseña»; el backend responde 422. */
                    <button
                      onClick={() => setPorRestablecer(u)}
                      className="btn-secondary" style={{ padding: '9px 14px', fontSize: '0.84rem' }}>
                      <RotateCcw size={15} /> {t('usuarios.restablecer')}
                    </button>
                  ))}
                  {/* **Sobre la propia ficha no se ofrece ni el rol ni la
                      baja.** El backend ya lo impide —devuelve 422 "No puede
                      desactivar su propia cuenta"—, así que dejarlos puestos
                      solo servía para invitar a un clic que termina en un
                      error. Un admin que quiera dejar de serlo se lo pide a
                      otro, que es justo lo que la regla protege: que el sitio
                      no se quede sin nadie que administre. */}
                  {u.id !== sesion?.id && (
                    <>
                      {/* El rol decide qué ve alguien cuando entra, así que
                          sobre una baja es un mando sin destino. Vuelve con el
                          acceso. */}
                      {/* Solo a quien reporta: a TI la prioridad no se le
                          restringe, así que la casilla no mandaría nada. */}
                      {u.activo && u.rol !== 'admin' && (
                        <label className="interruptor" title={t('usuarios.prioridad_alta_ayuda')}>
                          <input type="checkbox" checked={u.puede_usar_prioridad_alta !== false}
                            onChange={(e) => cambiarPrioridadAlta(u, e.target.checked)} />
                          {t('usuarios.prioridad_alta')}
                        </label>
                      )}
                      {u.activo && (
                      <Selector className="form-select" value={u.rol}
                        onChange={(e) => cambiarRol(u, e.target.value)}
                        /* `width: auto` porque el desplegable de una fila de
                           acciones no es un campo de formulario: `.selector`
                           trae `width: 100%` para llenar su `.form-group`, y
                           aquí eso lo hacía acaparar la fila entera y tirar la
                           equis de dar de baja a una tercera línea. */
                        style={{ padding: '8px 10px', fontSize: '0.84rem', minWidth: '110px', width: 'auto' }}>
                        <option value="usuario">{t('usuarios.rol_usuario')}</option>
                        <option value="admin">{t('usuarios.rol_admin')}</option>
                      </Selector>
                      )}
                      {/* **Se pregunta antes, y se pregunta qué.** Cortarle
                          el acceso a alguien es más grave que restablecerle la
                          contraseña, y eso ya preguntaba: aquí bastaba un clic
                          en una equis pequeña, pegada al desplegable de rol, y
                          la persona se quedaba fuera sin que nadie se
                          enterara. Ahora abre el diálogo donde se elige entre
                          la baja —reversible— y la eliminación, que no lo es.

                          A quien ya está de baja se le ofrece antes el camino
                          de vuelta: la equis sigue estando, pero el verde va
                          primero porque es lo que se busca al abrir el filtro
                          de bajas. */}
                      {!u.activo && (
                        <button onClick={() => setPorReactivar(u)}
                          className="btn-secondary btn-secondary--exito"
                          style={{ padding: '9px 13px' }}
                          title={t('usuarios.reactivar')}>
                          <Check size={15} />
                        </button>
                      )}
                      <button onClick={() => setPorQuitar(u)}
                        className="btn-secondary btn-secondary--peligro"
                        style={{ padding: '9px 13px' }}
                        title={t('usuarios.quitar')}>
                        <X size={15} />
                      </button>
                    </>
                  )}
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
/**
 * Quitar a alguien: dos operaciones distintas detrás de la misma equis.
 *
 * **Por qué no es una sola pregunta.** Dar de baja y eliminar se piden en el
 * mismo momento —"esta persona ya no trabaja aquí"— pero no son lo mismo ni de
 * lejos: una corta el acceso y se deshace mañana, la otra saca a la persona
 * del padrón para siempre. Ofrecerlas como un solo "¿seguro?" obliga a elegir
 * sin saber que había otra opción, y la que se ejecuta por descuido es la que
 * no tiene vuelta.
 *
 * Así que el diálogo primero enseña las dos con lo que hace cada una, y solo
 * la irreversible pide una segunda confirmación. La baja no la pide: se
 * deshace con un clic desde el filtro de bajas.
 */
const DialogoQuitar = ({ usuario, onCerrar, onBaja, onEliminar }) => {
  const { t } = useTranslation();
  // 'elegir' | 'eliminar'. La segunda pantalla es la del punto de no retorno.
  const [paso, setPaso] = useState('elegir');

  const Opcion = ({ icono, titulo, texto, onClick, peligro }) => (
    <button type="button" onClick={onClick} style={{
      display: 'flex', gap: '13px', textAlign: 'left', width: '100%',
      padding: '15px 16px', borderRadius: 'var(--radius-md)',
      border: `1px solid ${peligro ? 'var(--peligro-borde)' : 'var(--border-color)'}`,
      background: peligro ? 'var(--peligro-bg)' : 'var(--bg-tertiary)',
      color: 'inherit', cursor: 'pointer'
    }}>
      <span style={{ flexShrink: 0, marginTop: '2px', color: peligro ? 'var(--peligro)' : 'var(--text-secondary)' }}>
        {icono}
      </span>
      <span>
        <span style={{
          display: 'block', fontWeight: 700, fontSize: '0.95rem',
          color: peligro ? 'var(--peligro)' : 'var(--text-primary)', marginBottom: '4px'
        }}>
          {titulo}
        </span>
        <span style={{ display: 'block', color: 'var(--text-secondary)', fontSize: '0.85rem', lineHeight: 1.45 }}>
          {texto}
        </span>
      </span>
    </button>
  );

  return (
    <CapaModal onCerrar={onCerrar} etiqueta={usuario.nombre}>
      <div onClick={(e) => e.stopPropagation()} className="apple-card animate-scale-in"
        style={{ padding: '28px', maxWidth: '480px', width: '100%' }}>

        {paso === 'elegir' ? (
          <>
            <h2 style={{ fontSize: '1.1rem', fontWeight: 700, color: 'var(--text-primary)', lineHeight: 1.35, marginBottom: '18px' }}>
              {t('usuarios.quitar_titulo', { nombre: usuario.nombre })}
            </h2>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginBottom: '20px' }}>
              {/* A quien ya está de baja no se le ofrece darlo de baja otra
                  vez: la única salida que le queda es la definitiva. */}
              {usuario.activo && (
                <Opcion
                  icono={<X size={18} />}
                  titulo={t('usuarios.opcion_baja')}
                  texto={t('usuarios.opcion_baja_texto')}
                  onClick={onBaja}
                />
              )}
              <Opcion
                peligro
                icono={<Trash2 size={18} />}
                titulo={t('usuarios.opcion_eliminar')}
                texto={t('usuarios.opcion_eliminar_texto')}
                onClick={() => setPaso('eliminar')}
              />
            </div>
            <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
              <button type="button" onClick={onCerrar} className="btn-secondary" style={{ padding: '10px 18px' }}>
                {t('comun.cancelar')}
              </button>
            </div>
          </>
        ) : (
          <>
            <div style={{ display: 'flex', gap: '14px', marginBottom: '18px' }}>
              <AlertTriangle size={22} color="var(--peligro)" style={{ flexShrink: 0, marginTop: '2px' }} />
              <h2 style={{ fontSize: '1.1rem', fontWeight: 700, color: 'var(--text-primary)', lineHeight: 1.35 }}>
                {t('usuarios.eliminar_titulo', { nombre: usuario.nombre })}
              </h2>
            </div>

            {/* Lo que se conserva va primero y en verde: es la duda que
                frena la mano, y la respuesta es que no se pierde nada. */}
            <div style={{
              display: 'flex', gap: '10px', padding: '13px 15px', marginBottom: '10px',
              borderRadius: 'var(--radius-md)',
              background: 'var(--status-resuelto-bg)', color: 'var(--status-resuelto-text)',
              fontSize: '0.85rem', lineHeight: 1.45
            }}>
              <Check size={16} style={{ flexShrink: 0, marginTop: '2px' }} />
              <span>{t('usuarios.eliminar_conserva')}</span>
            </div>
            <div style={{
              display: 'flex', gap: '10px', padding: '13px 15px', marginBottom: '10px',
              borderRadius: 'var(--radius-md)',
              background: 'var(--peligro-bg)', color: 'var(--peligro)',
              fontSize: '0.85rem', lineHeight: 1.45
            }}>
              <Trash2 size={16} style={{ flexShrink: 0, marginTop: '2px' }} />
              <span>{t('usuarios.eliminar_borra')}</span>
            </div>

            {/* Un equipo asignado a alguien que ya no existe se queda en el
                inventario a nombre de un fantasma. No se impide —a veces la
                persona ya no está para devolverlo— pero se avisa. */}
            {usuario.equipos_a_cargo > 0 && (
              <div style={{
                display: 'flex', gap: '10px', padding: '13px 15px', marginBottom: '10px',
                borderRadius: 'var(--radius-md)',
                background: 'var(--status-espera-proveedor-bg)',
                color: 'var(--status-espera-proveedor-text)',
                fontSize: '0.85rem', lineHeight: 1.45
              }}>
                <Laptop size={16} style={{ flexShrink: 0, marginTop: '2px' }} />
                <span>{t('usuarios.eliminar_equipos', { count: usuario.equipos_a_cargo })}</span>
              </div>
            )}

            <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end', marginTop: '20px' }}>
              <button type="button" onClick={() => setPaso('elegir')} className="btn-secondary" style={{ padding: '10px 18px' }}>
                {t('comun.cancelar')}
              </button>
              <button type="button" onClick={onEliminar} className="btn-primary btn-primary--peligro" style={{ padding: '10px 18px' }}>
                <Trash2 size={15} /> {t('usuarios.eliminar_confirmar')}
              </button>
            </div>
          </>
        )}
      </div>
    </CapaModal>
  );
};

/* ================================================================ */
const TarjetaCodigo = ({ datos, onCerrar }) => {
  const { t } = useTranslation();
  // null = sin intentar todavía; true = en el portapapeles; false = no se pudo.
  const [copiado, setCopiado] = useState(null);
  const cajaCodigo = useRef(null);

  /* **El botón dice la verdad sobre lo que pasó.**

     Antes llamaba a `navigator.clipboard.writeText` a secas y se tragaba el
     fallo. Sin TLS esa API no existe —el portal responde por HTTP— así que en
     planta el botón no hacía nada y tampoco lo decía: el código no llegaba al
     portapapeles y quien daba el alta se enteraba al pegarlo. Ahora el
     respaldo de `copiarTexto` cubre ese caso, y si tampoco puede, se deja el
     código seleccionado y el botón pide un Ctrl+C en vez de callarse. */
  const copiar = async () => {
    const ok = await copiarTexto(datos.codigo);
    setCopiado(ok);
    if (!ok) seleccionarContenido(cajaCodigo.current);
    // El aviso de fallo se queda: es una instrucción, no una confirmación.
    if (ok) setTimeout(() => setCopiado(null), 2500);
  };

  return (
    <CapaModal onCerrar={onCerrar}>
      <div onClick={(e) => e.stopPropagation()} className="apple-card animate-scale-in"
        style={{ padding: '32px', maxWidth: '480px', width: '100%', textAlign: 'center' }}>
        <KeyRound size={38} color="var(--accent-primary)" style={{ margin: '0 auto 16px' }} />
        <h2 style={{ fontSize: '1.25rem', fontWeight: '700', marginBottom: '8px', color: 'var(--text-primary)' }}>
          {t('usuarios.codigo_titulo')}
        </h2>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', marginBottom: '20px' }}>
          {datos.numero_empleado || datos.email}
        </p>

        {/* `user-select: all` para que un clic dentro seleccione el código
            entero: es el camino de salida cuando el portapapeles está cerrado
            y hay que copiarlo a mano. */}
        <div ref={cajaCodigo} style={{
          fontFamily: 'var(--font-codigo)', fontSize: '2rem', fontWeight: '700',
          letterSpacing: '0.16em', color: 'var(--accent-primary)',
          background: 'var(--bg-tertiary)', padding: '20px',
          borderRadius: 'var(--radius-md)', marginBottom: '14px',
          userSelect: 'all', cursor: 'text'
        }}>
          {datos.codigo}
        </div>

        <button onClick={copiar} className="btn-secondary"
          style={{ padding: '9px 18px', fontSize: '0.86rem', marginBottom: copiado === false ? '10px' : '18px' }}>
          <Copy size={15} /> {copiado ? t('usuarios.copiado') : t('usuarios.copiar')}
        </button>

        {copiado === false && (
          <div role="status" style={{
            color: 'var(--status-espera-proveedor-text)', fontSize: '0.82rem',
            lineHeight: 1.45, marginBottom: '18px'
          }}>
            {t('usuarios.copiar_manual')}
          </div>
        )}

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

        <button onClick={onCerrar} className="btn-acento" style={{ padding: '12px 26px' }}>
          {t('usuarios.ya_lo_anote')}
        </button>
      </div>
    </CapaModal>
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
    <CapaModal>
      <Formulario onSubmit={enviar} onClick={(e) => e.stopPropagation()}
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
            background: 'var(--peligro-bg)', border: '1px solid var(--peligro-borde)', color: 'var(--peligro)',
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
              color: coinciden ? 'var(--status-resuelto-text)' : 'var(--peligro)'
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
          <button type="submit" className="btn-acento"
            disabled={!larga || !coinciden || enviando} style={{ padding: '10px 18px' }}>
            <Check size={15} /> {enviando ? t('activar.activando') : t('usuarios.asistida_confirmar')}
          </button>
        </div>
      </Formulario>
    </CapaModal>
  );
};

/* ================================================================ */
/** Con una sola planta no hay nada que repartir: se dice, y dónde se añade otra. */
const NotaUnaPlanta = () => {
  const { t } = useTranslation();
  return (
    <div className="nota-suave" style={{ marginTop: '10px' }}>
      {t('plantas.una_sola')}{' '}
      <Link to="/personas/plantas" className="boton-texto" style={{ padding: 0 }}>{t('plantas.ir_a_plantas')}</Link>
    </div>
  );
};

/** Las plantas de una persona. Si viene `rol`, se guarda junto (dejar de ser TI). */
const DialogoPlantas = ({ usuario, rol, plantas, onCerrar, onGuardado }) => {
  const { t } = useTranslation();
  const [elegidas, setElegidas] = useState((usuario.plantas || []).map((p) => p.id));
  const [aviso, setAviso] = useState('');
  const [enviando, setEnviando] = useState(false);

  const guardar = async (e) => {
    e.preventDefault();
    if (!elegidas.length) { setAviso(t('plantas.al_menos_una')); return; }
    setEnviando(true);
    try {
      await api.patch(`/admin/usuarios/${usuario.id}`, rol ? { rol, plantas: elegidas } : { plantas: elegidas });
      onGuardado();
    } catch (err) {
      setAviso(err.response?.data?.detail || t('usuarios.error_accion'));
      setEnviando(false);
    }
  };

  return (
    <CapaModal onCerrar={onCerrar} etiqueta={t('plantas.de_persona', { nombre: usuario.nombre })}>
      <Formulario onSubmit={guardar} className="apple-card animate-scale-in"
        onClick={(e) => e.stopPropagation()}
        style={{ width: '100%', maxWidth: '520px', padding: '28px' }}>
        <h3 id="plantas-persona-rotulo" style={{ fontSize: '1.1rem', fontWeight: 700, marginBottom: '6px', color: 'var(--text-primary)' }}>
          {t('plantas.de_persona', { nombre: usuario.nombre })}
        </h3>
        <p style={{ fontSize: '0.86rem', color: 'var(--text-secondary)', marginBottom: '16px', lineHeight: 1.5 }}>
          {rol ? t('plantas.al_dejar_ti') : t('plantas.ayuda_persona')}
        </p>
        <PlantasMultiples plantas={plantas} value={elegidas} onChange={setElegidas} />
        {plantas.length <= 1 && <NotaUnaPlanta />}
        <Aviso texto={aviso} />
        <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end', marginTop: '18px' }}>
          <button type="button" onClick={onCerrar} className="btn-secondary" style={{ padding: '10px 18px' }}>
            <X size={15} /> {t('temas.cancelar')}
          </button>
          <button type="submit" className="btn-acento" disabled={enviando || !elegidas.length}
            style={{ padding: '10px 18px' }}>
            <Check size={15} /> {enviando ? t('temas.guardando') : t('temas.guardar')}
          </button>
        </div>
      </Formulario>
    </CapaModal>
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
  // En qué plantas trabaja. Con una sola planta se enseña igual, ya marcada:
  // escondida, la asignación parecía no existir.
  const [plantas] = usePlantas();
  const [plantasElegidas, setPlantasElegidas] = useState([]);
  const [enviando, setEnviando] = useState(false);

  useEffect(() => {
    if (plantas.length === 1 && plantasElegidas.length === 0) setPlantasElegidas([plantas[0].id]);
  }, [plantas]);

  useEffect(() => {
    api.get('/auth/requisitos-password')
      .then((r) => setDominios(lista(r.data.dominios_permitidos, 'los dominios permitidos')))
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
        area: area.trim() || null, rol,
        // TI es global y no lleva plantas; una persona, las elegidas (o la
        // única que haya, que decide el backend).
        plantas: rol === 'admin' ? [] : plantasElegidas
      });
      onCreado(res.data);
    } catch (err) {
      onError(err.response?.data?.detail || t('usuarios.error_alta'));
      setEnviando(false);
    }
  };

  return (
    <Formulario onSubmit={enviar} className="apple-card animate-scale-in"
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
          <Selector className="form-select" value={rol} onChange={(e) => setRol(e.target.value)}>
            <option value="usuario">{t('usuarios.rol_usuario')}</option>
            <option value="admin">{t('usuarios.rol_admin')}</option>
          </Selector>
        </div>
      </div>

      {plantas.length > 0 && (
        <div className="form-group">
          <label id="plantas-persona-rotulo">{t('plantas.plantas_persona')}</label>
          {/* TI es global: no se le asignan plantas, y el selector no se
              ofrece para no dar a entender que limita algo. */}
          {rol === 'admin' ? (
            <div className="nota-suave">{t('plantas.ti_global_ayuda')}</div>
          ) : (
            <>
              <PlantasMultiples plantas={plantas} value={plantasElegidas} onChange={setPlantasElegidas} />
              <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginTop: '6px' }}>
                {t('plantas.ayuda_persona')}
              </div>
              {plantas.length === 1 && <NotaUnaPlanta />}
            </>
          )}
        </div>
      )}

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
        <button type="submit" className="btn-acento"
          disabled={enviando || !nombre || !numeroEmpleado
            || (plantas.length > 0 && rol !== 'admin' && plantasElegidas.length === 0)}
          style={{ padding: '10px 18px' }}>
          <Check size={15} /> {enviando ? t('temas.guardando') : t('usuarios.dar_de_alta')}
        </button>
      </div>
    </Formulario>
  );
};

export default Usuarios;
