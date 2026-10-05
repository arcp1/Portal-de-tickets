import React, { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { BotonCopiar } from '../components/Folio';
import api from '../api/client';
import { useAuth } from '../context/AuthContext';
import StatusBadge from '../components/StatusBadge';
import AdjuntosTicket from '../components/AdjuntosTicket';
import { EtiquetaSLA } from '../components/AvisoHorario';
import { ArrowLeft, MessageSquare, Send, AlertTriangle, CheckCircle, Wrench, X, XCircle, Camera, Plus } from 'lucide-react';
import CapaModal from '../components/CapaModal';
import Confirmacion from '../components/Confirmacion';
import { useEventoPortal } from '../context/Eventos';
import Selector from '../components/Selector';
import Formulario from '../components/Formulario';
import lista from '../lib/lista';
import forma from '../lib/forma';
import { avisar, mensajeDeError } from '../lib/avisos';
import EncuestaSatisfaccion from '../components/EncuestaSatisfaccion';
import { EtiquetaPlanta } from '../lib/plantas';
import { EditorImagenes, GaleriaImagenes } from '../components/ImagenesConocimiento';

const PRIORIDADES = ['baja', 'media', 'alta', 'critica'];

// Estados que exigen documentar la solución. Debe coincidir con
// ESTADOS_DE_CIERRE en backend/app/api/tickets.py.
const ESTADOS_DE_CIERRE = ['resuelto', 'cerrado'];
// Ya fuera de la cola de TI. Igual que ESTADOS_TERMINADOS en backend/app/models.
const ESTADOS_TERMINADOS = ['resuelto', 'cerrado', 'cancelado'];
// Igual que SOLUCION_MIN_LONGITUD en el backend.
const SOLUCION_MIN_LONGITUD = 20;

const TicketDetail = () => {
  const { id } = useParams();
  const { t, i18n } = useTranslation();
  const { user } = useAuth();
  const navigate = useNavigate();

  const [ticket, setTicket] = useState(null);
  const [usuarios, setUsuarios] = useState([]);
  const [aviso, setAviso] = useState('');
  const [loading, setLoading] = useState(true);
  // El motivo por el que no hay ticket, si no hay. No es lo mismo "no existe"
  // que "no se pudo preguntar": ver `fetchTicket`.
  const [errorCarga, setErrorCarga] = useState('');
  // El comentario a medio escribir se guarda por ticket, como el borrador del
  // formulario nuevo: una sesión que caduca al pulsar "Enviar" ya no se lo
  // lleva. En `sessionStorage`, que dura lo que la pestaña.
  const claveComentario = `portal_borrador_comentario_${user.id}_${id}`;
  const [newComment, setNewComment] = useState(() => {
    try { return sessionStorage.getItem(claveComentario) || ''; } catch { return ''; }
  });
  useEffect(() => {
    try {
      if (newComment.trim()) sessionStorage.setItem(claveComentario, newComment);
      else sessionStorage.removeItem(claveComentario);
    } catch { /* sin almacenamiento, sin borrador */ }
  }, [newComment, claveComentario]);
  const [isInternal, setIsInternal] = useState(false);
  const [submittingComment, setSubmittingComment] = useState(false);

  // Cierre con solución obligatoria.
  const [estadoPendiente, setEstadoPendiente] = useState(null);
  const [solucion, setSolucion] = useState('');
  // Lo que se probó y NO era. Opcional, pero es lo que le ahorra media hora al
  // siguiente que atienda la misma falla.
  const [descartado, setDescartado] = useState('');
  const [errorCierre, setErrorCierre] = useState('');
  const [guardandoCierre, setGuardandoCierre] = useState(false);
  // Las capturas de la solución mientras se escribe: se suben cuando el
  // cierre se guarda, no antes. Cancelar no deja nada colgado del ticket.
  const imagenesCierre = useRef(null);
  // TI añade o quita capturas de una solución ya escrita.
  const [editandoImagenes, setEditandoImagenes] = useState(false);
  const [creandoFicha, setCreandoFicha] = useState(false);
  // Aparte de `errorCierre`: ése sólo se pinta dentro del diálogo de cierre, y
  // este botón vive fuera. Un error ahí no se vería.
  const [avisoFicha, setAvisoFicha] = useState('');
  // Cancelar pide confirmación: es lo único irreversible que puede hacer
  // quien reporta, y el botón está a un dedo del de volver.
  const [porCancelar, setPorCancelar] = useState(false);
  const [cancelando, setCancelando] = useState(false);
  // Guardas que cambian en el acto, no al volver a pintar: dos toques
  // seguidos en «Comentar» publicaban el comentario dos veces, y dos en
  // «Sí, cancelar» enseñaban un error justo después del éxito.
  const comentando = useRef(false);
  const cancelandoYa = useRef(false);

  useEffect(() => {
    fetchTicket();
  }, [id]);

  useEffect(() => {
    // Para poder asignar el ticket. Solo admin puede leer el padron.
    if (user.rol !== 'admin') return;
    api.get('/auth/usuarios').then((r) => setUsuarios(lista(r.data, 'los usuarios'))).catch(() => setUsuarios([]));
  }, [user.rol]);

  /**
   * Convierte este ticket en una ficha del catálogo visual.
   *
   * Se lleva la descripción, la solución, lo que se descartó y las fotos que
   * ya están adjuntas aquí. Nace en borrador —nadie publica sin revisar— y se
   * abre la pantalla del catálogo para ponerle título y frases.
   */
  // Sin una foto adjunta no hay nada que enseñar, así que el botón no se
  // ofrece: llevaría a una ficha que no puede hacer su única pregunta.
  const tieneFoto = (ticket?.adjuntos || []).some(
    (a) => (a.tipo_mime || '').startsWith('image/')
  );

  const crearFichaVisual = async () => {
    setCreandoFicha(true);
    try {
      setAvisoFicha('');
      await api.post(`/admin/visual/desde-ticket/${id}`);
      navigate('/conocimiento/catalogo');
    } catch (err) {
      setAvisoFicha(err.response?.data?.detail || t('ticket.error_ficha_visual'));
    } finally {
      setCreandoFicha(false);
    }
  };

  const cancelarTicket = async () => {
    if (cancelandoYa.current) return;
    cancelandoYa.current = true;
    setPorCancelar(false);
    setCancelando(true);
    setAviso('');
    try {
      const res = await api.post(`/tickets/${id}/cancelar`);
      // Un 200 con otro cuerpo dejaría la ficha a medio pintar: se trata como
      // el fallo que es y se vuelve a pedir el ticket, que sí se sabe leer.
      if (!forma(res.data, ['id', 'estado', 'comentarios'], 'el ticket cancelado')) {
        throw new Error('Respuesta de cancelación con otra forma');
      }
      setTicket(res.data);
      avisar(t('ticket.cancelado_ok'), { tono: 'exito' });
    } catch (err) {
      setAviso(mensajeDeError(err, t('ticket.error_cancelar')));
      fetchTicket();
    } finally {
      cancelandoYa.current = false;
      setCancelando(false);
    }
  };

  const fetchTicket = async () => {
    // Una URL editada a mano —/tickets/abc, /tickets/-1— no es un ticket que
    // exista. Preguntarlo al API devolvía su validación tal cual, con el
    // nombre técnico del parámetro: "ticket_id debe ser un número entero".
    if (!/^[1-9]\d{0,9}$/.test(id) || Number(id) > 2147483647) {
      setTicket(null);
      setErrorCarga(t('ticket.no_encontrado'));
      setLoading(false);
      return;
    }
    try {
      const res = await api.get(`/tickets/${id}`);
      setTicket(res.data);
      setErrorCarga('');
    } catch (err) {
      // **Un 404 es "no existe"; lo demás es "no se pudo saber".** Antes todo
      // fallo acababa en "Ticket no encontrado": con la red caída o el backend
      // reiniciándose, el portal le decía a la persona que su ticket no
      // existía. Solo el 404 lo afirma.
      setErrorCarga(err.response?.status === 404
        ? t('ticket.no_encontrado')
        : mensajeDeError(err, t('ticket.error_cargar')));
    } finally {
      setLoading(false);
    }
  };

  const handleStatusChange = async (nuevoEstado) => {
    // Resolver o cerrar exige documentar la solución. Sin ella el ticket no
    // se puede indexar en la base de conocimiento.
    if (ESTADOS_DE_CIERRE.includes(nuevoEstado)) {
      setSolucion(ticket.solucion || '');
      setDescartado(ticket.descartado || '');
      setErrorCierre('');
      setEstadoPendiente(nuevoEstado);
      return;
    }

    await guardarCampo({ estado: nuevoEstado });
  };

  /**
   * Cambios que no exigen documentar nada: prioridad y responsable.
   *
   * El backend acepta los dos desde siempre; lo que faltaba era la manera de
   * mandarlos. Sin esto un ticket no se podia asignar a nadie ni reclasificar,
   * y cambiar la prioridad es lo que recalcula el compromiso de SLA.
   */
  const guardarCampo = async (cambios) => {
    // **Optimista.** El cambio se pinta antes de que el servidor conteste, y
    // se deshace si contesta que no.
    //
    // El motivo no es la velocidad, es la duda. Con el orden anterior —pedir,
    // esperar, pintar— el desplegable se quedaba en el valor viejo unas
    // décimas y la reacción natural es volver a tocarlo; en una terminal de
    // planta con la red cargada, esas décimas son un segundo largo. Pintar
    // primero elimina la pregunta "¿se guardó?" sin mentir: si falla, el
    // campo vuelve a donde estaba y aparece el aviso.
    const previo = ticket;
    setTicket((actual) => ({ ...actual, ...cambios }));
    setAviso('');
    try {
      const res = await api.patch(`/tickets/${id}`, cambios);
      // La respuesta manda: trae campos que el cliente no puede calcular,
      // como el vencimiento recalculado al cambiar la prioridad.
      setTicket(res.data);
    } catch (err) {
      setTicket(previo);
      setAviso(err.response?.data?.detail || t('ticket.error_guardar'));
    }
  };

  /** El detalle también escucha: si alguien comenta el ticket que tienes
   *  abierto, aparece sin que tengas que recargar. */
  useEventoPortal('tickets', async () => {
    try {
      const res = await api.get(`/tickets/${id}`);
      setTicket(res.data);
    } catch { /* si falla, lo que hay en pantalla sigue siendo válido */ }
  });

  const confirmarCierre = async (e) => {
    e.preventDefault();
    if (solucion.trim().length < SOLUCION_MIN_LONGITUD) return;

    setGuardandoCierre(true);
    setErrorCierre('');
    try {
      const res = await api.patch(`/tickets/${id}`, {
        estado: estadoPendiente,
        solucion: solucion.trim(),
        descartado: descartado.trim()
      });
      setTicket(res.data);
      const habia = imagenesCierre.current?.hayPendientes();
      if (habia) {
        const fallidas = await imagenesCierre.current.subirPendientes(res.data.id);
        if (fallidas) {
          avisar(t('imagenes.algunas_no_subieron', { count: fallidas }), { tono: 'atencion' });
        }
        // El PATCH respondió antes de que existieran: se pide el ticket de
        // nuevo para que la solución aparezca con sus capturas.
        try { setTicket((await api.get(`/tickets/${id}`)).data); } catch { /* queda lo de arriba */ }
      }
      setEstadoPendiente(null);
      setSolucion('');
    } catch (err) {
      setErrorCierre(err.response?.data?.detail || t('ticket.error_cierre'));
    } finally {
      setGuardandoCierre(false);
    }
  };

  const cancelarCierre = () => {
    setEstadoPendiente(null);
    setSolucion('');
    setErrorCierre('');
  };

  const handleAddComment = async (e) => {
    e.preventDefault();
    if (!newComment.trim() || comentando.current) return;
    comentando.current = true;
    setSubmittingComment(true);
    try {
      await api.post(`/tickets/${id}/comments`, {
        comentario: newComment,
        es_interno: user.rol === 'admin' ? isInternal : false
      });
      setNewComment('');
      setIsInternal(false);
      setAviso('');
      fetchTicket();
    } catch (err) {
      setAviso(err.response?.data?.detail || t('ticket.error_comentario'));
    } finally {
      comentando.current = false;
      setSubmittingComment(false);
    }
  };

  if (loading) {
    return <div className="page-container" style={{ textAlign: 'center', padding: '60px', color: 'var(--text-muted)' }}>{t('ticket.cargando')}</div>;
  }

  if (!ticket) {
    // Con el aviso a secas la pantalla era un callejón sin salida: un folio
    // viejo o mal tecleado dejaba a la persona sin nada donde pulsar y sin
    // barra de navegación en la que apoyarse desde el móvil. La salida al
    // tablero va aquí por la misma razón que en la ficha que sí carga.
    return (
      <div className="page-container" style={{ textAlign: 'center', padding: '60px' }}>
        <div style={{ color: 'var(--text-muted)', marginBottom: '20px' }}>{errorCarga || t('ticket.no_encontrado')}</div>
        <button onClick={() => navigate('/')} className="btn-secondary enlace-volver">
          <ArrowLeft size={16} />
          {t('comun.volver')}
        </button>
      </div>
    );
  }

  // Resuelto, cerrado o cancelado: quien lo reportó ya solo lo lee. El backend
  // rechaza comentarios y archivos con 409; aquí ni se ofrecen.
  const soloLectura = user.rol !== 'admin' && ESTADOS_TERMINADOS.includes(ticket.estado);

  return (
    <div className="page-container animate-fade-in">
      <button onClick={() => navigate('/')} className="btn-secondary enlace-volver" style={{ marginBottom: '24px' }}>
        <ArrowLeft size={16} />
        {t('comun.volver')}
      </button>

      {/* Header Info Card */}
      <div className="apple-card" style={{ padding: '32px', marginBottom: '24px' }}>
        <div style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          gap: '16px',
          flexWrap: 'wrap',
          marginBottom: '20px'
        }}>
          <div>
            {/* `wrap`, como las etiquetas del tablero: en el teléfono folio,
                copiar, estado y vencimiento no caben en una línea, y sin
                partirse empujaban la ficha 124 px fuera de la pantalla —medido
                a 360 px— con el folio aplastado en tres renglones. */}
            <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: '8px 16px', marginBottom: '8px' }}>
              <h1 className="page-title" style={{ fontSize: '1.75rem' }}>
                {ticket.folio}
              </h1>
              {/* El folio se copia desde un botón al lado y no pulsando el
                  título: un `<h1>` que además es un botón deja de anunciarse
                  como encabezado, y el encabezado es lo que da el sitio en un
                  lector de pantalla. */}
              <BotonCopiar texto={ticket.folio}
                etiqueta={t('comun.copiar_folio', { folio: ticket.folio })} />
              <StatusBadge estado={ticket.estado} />
              <EtiquetaSLA venceEn={ticket.vence_en} estado={ticket.estado} />
            </div>
            <div className="rotulo-seccion">
              {t('ticket.creado_el', { fecha: new Date(ticket.creado_en).toLocaleString(i18n.language) })}
            </div>
          </div>

          {/* **Cancelar: solo quien lo reportó, y solo mientras siga en la
              cola.** Lo único que puede cambiar de su ticket; resolverlo o
              cerrarlo es de TI, y uno ya terminado no vuelve atrás. */}
          {ticket.usuario_id === user.id && !ESTADOS_TERMINADOS.includes(ticket.estado) && (
            <button type="button" onClick={() => setPorCancelar(true)} disabled={cancelando}
              className="btn-secondary btn-secondary--peligro" style={{ alignSelf: 'center' }}>
              <XCircle size={16} />
              {cancelando ? t('ticket.cancelando') : t('ticket.cancelar_ticket')}
            </button>
          )}

          {/* Admin Controls. No sobre uno cancelado: el backend ya no lo deja
              mover, y ofrecer los desplegables solo invitaría a un error. */}
          {user.rol === 'admin' && ticket.estado !== 'cancelado' && (
            <div style={{
              display: 'flex', alignItems: 'flex-end', gap: '12px', flexWrap: 'wrap',
              background: 'var(--bg-tertiary)', padding: '12px 16px', borderRadius: 'var(--radius-md)'
            }}>
              <label style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
                <span style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', fontWeight: '500' }}>
                  {t('ticket.estado')}
                </span>
                <Selector
                  className="form-select"
                  value={ticket.estado}
                  onChange={(e) => handleStatusChange(e.target.value)}
                  style={{ padding: '8px 14px', fontSize: '0.9rem', minWidth: '150px' }}
                >
                  <option value="abierto">{t('ticket.estado_abierto')}</option>
                  <option value="en_proceso">{t('ticket.estado_en_proceso')}</option>
                  <option value="espera_proveedor">{t('ticket.estado_espera_proveedor')}</option>
                  <option value="resuelto">{t('ticket.estado_resuelto')}</option>
                  <option value="cerrado">{t('ticket.estado_cerrado')}</option>
                </Selector>
              </label>

              {/* Cambiar la prioridad recalcula el vencimiento del SLA. */}
              <label style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
                <span style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', fontWeight: '500' }}>
                  {t('ticket.prioridad')}
                </span>
                <Selector
                  className="form-select"
                  value={ticket.prioridad}
                  onChange={(e) => guardarCampo({ prioridad: e.target.value })}
                  style={{ padding: '8px 14px', fontSize: '0.9rem', minWidth: '130px' }}
                >
                  {PRIORIDADES.map((pr) => (
                    <option key={pr} value={pr}>
                      {t(`ticket.prioridad_${pr}`, { defaultValue: pr })}
                    </option>
                  ))}
                </Selector>
              </label>

              <label style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
                <span style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', fontWeight: '500' }}>
                  {t('ticket.asignado_a')}
                </span>
                <Selector
                  className="form-select"
                  value={ticket.asignado_a || ''}
                  onChange={(e) => guardarCampo({
                    asignado_a: e.target.value ? parseInt(e.target.value, 10) : null
                  })}
                  style={{ padding: '8px 14px', fontSize: '0.9rem', minWidth: '170px' }}
                >
                  <option value="">{t('ticket.sin_asignar')}</option>
                  {/* Solo TI: el backend rechaza a los demás. Se conserva a
                      quien ya lo tenga asignado aunque no lo sea —un ticket
                      de antes de la regla—, para que el selector diga su
                      nombre y no "Sin asignar". */}
                  {usuarios
                    .filter((u) => u.rol === 'admin' || u.id === ticket.asignado_a)
                    .map((u) => (
                      <option key={u.id} value={u.id}>{u.nombre}</option>
                    ))}
                </Selector>
              </label>
            </div>
          )}
        </div>

        {ticket.estado === 'cancelado' && (
          <div className="aviso-barra aviso-barra--atencion" role="status">
            <XCircle size={18} aria-hidden="true" />
            <span>
              {t('ticket.fue_cancelado', {
                fecha: ticket.cancelado_en
                  ? new Date(ticket.cancelado_en).toLocaleString(i18n.language)
                  : ''
              })}
            </span>
          </div>
        )}

        {aviso && (
          <div className="animate-scale-in" style={{
            display: 'flex', alignItems: 'center', gap: '10px',
            background: 'var(--status-espera-proveedor-bg)',
            color: 'var(--status-espera-proveedor-text)',
            padding: '13px 16px', borderRadius: 'var(--radius-md)',
            marginBottom: '18px', fontSize: '0.9rem'
          }}>
            <AlertTriangle size={17} /> {aviso}
          </div>
        )}

        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
          gap: '20px',
          padding: '24px',
          background: 'var(--bg-tertiary)',
          borderRadius: 'var(--radius-md)',
          marginBottom: '28px'
        }}>
          <div>
            <div className="rotulo-dato">{t('ticket.creado_por')}</div>
            <div className="dato-valor">{ticket.usuario?.nombre}</div>
          </div>
          <div>
            <div className="rotulo-dato">{t('ticket.categoria')}</div>
            <div className="dato-valor">{t(`new_ticket.category_${ticket.categoria}`, { defaultValue: ticket.categoria })}</div>
          </div>
          {ticket.sitio && (
            <div>
              <div className="rotulo-dato">{t('plantas.planta')}</div>
              <div className="dato-valor"><EtiquetaPlanta planta={ticket.sitio} /></div>
            </div>
          )}
          {/* **La prioridad y el responsable, una sola vez en la ficha.**

              Al administrador ya se los enseña el bloque de arriba, y ahí
              además puede cambiarlos: repetirlos aquí en solo lectura ponía el
              mismo dato dos veces a diez centímetros —"Crítica" debajo de un
              desplegable que dice "Crítica"— y obligaba a mirar dos sitios
              para saber si lo que veías era el valor o el mando.

              A quien no es administrador no le sale ese bloque, así que para
              esa persona este es el único sitio donde constan. */}
          {user.rol !== 'admin' && (
            <>
              <div>
                <div className="rotulo-dato">{t('ticket.prioridad')}</div>
                <div className="dato-valor">{t(`ticket.prioridad_${ticket.prioridad}`, { defaultValue: ticket.prioridad })}</div>
              </div>
              <div>
                <div className="rotulo-dato">{t('ticket.asignado_a')}</div>
                <div className="dato-valor">
                  {ticket.asignado_usuario?.nombre || t('ticket.sin_asignar')}
                </div>
              </div>
            </>
          )}
          {/* Como en el tablero: un cancelado no pasó por ningún canal, y el
              "técnico" con el que nace diría que alguien de TI lo resolvió. */}
          {ticket.estado !== 'cancelado' && (
          <div>
            <div className="rotulo-dato">{t('ticket.canal')}</div>
            <div className="dato-valor">
              {/* El valor viene crudo de la base ("tecnico", "kb", "checklist"),
                  y sin traducir se quedaba en castellano en los tres idiomas.
                  Las etiquetas ya existían para el panel de métricas. */}
              {ticket.canal_resolucion
                ? t(`metricas.canal_${ticket.canal_resolucion}`, { defaultValue: ticket.canal_resolucion })
                : t('ticket.canal_tecnico')}
            </div>
          </div>
          )}
        </div>

        <div>
          <h3 style={{ fontSize: '1rem', fontWeight: '600', color: 'var(--text-primary)', marginBottom: '12px' }}>
            {t('ticket.descripcion')}
          </h3>
          <div style={{
            fontSize: '1.05rem',
            lineHeight: '1.6',
            color: 'var(--text-primary)',
            background: 'var(--bg-secondary)',
            padding: '20px',
            borderRadius: 'var(--radius-md)',
            border: '1px solid var(--border-color)',
            boxShadow: 'var(--shadow-sm)'
          }}>
            {ticket.descripcion_original}
          </div>
        </div>

        {/* El resumen para TI que escribe la IA, aparte: la descripción de
            arriba es la del usuario, intacta. Solo aparece si se generó. */}
        {ticket.descripcion_normalizada && (
          <div style={{ marginTop: '20px' }}>
            <h3 style={{ fontSize: '1rem', fontWeight: '600', color: 'var(--text-primary)', marginBottom: '12px' }}>
              {t('ticket.descripcion_normalizada')}
            </h3>
            <div style={{
              fontSize: '1rem',
              lineHeight: '1.6',
              color: 'var(--text-secondary)',
              background: 'var(--bg-tertiary)',
              padding: '18px',
              borderRadius: 'var(--radius-md)'
            }}>
              {ticket.descripcion_normalizada}
            </div>
          </div>
        )}

        {/* La encuesta: la contesta quien reportó cuando queda resuelto. */}
        <EncuestaSatisfaccion
          ticket={ticket}
          usuario={user}
          onCalificado={(actualizado) => setTicket(actualizado)}
        />

        {/* Solución documentada */}
        {ticket.solucion && (
          <div style={{ marginTop: '24px' }}>
            <h3 style={{
              fontSize: '1rem',
              fontWeight: '600',
              color: 'var(--text-primary)',
              marginBottom: '12px',
              display: 'flex',
              alignItems: 'center',
              gap: '8px'
            }}>
              <Wrench size={18} color="var(--status-resuelto-text)" />
              {t('ticket.solucion')}
            </h3>
            <div style={{
              fontSize: '1.05rem',
              lineHeight: '1.6',
              color: 'var(--text-primary)',
              background: 'var(--status-resuelto-bg)',
              padding: '20px',
              borderRadius: 'var(--radius-md)',
              whiteSpace: 'pre-line'
            }}>
              {ticket.solucion}
            </div>

            {/* **Las capturas de cómo se resolvió.** Es lo que la persona
                abre para ver qué le hicieron, y una imagen de la
                configuración que se cambió se entiende sin leer el párrafo.
                A TI se le ofrece además añadir o quitar: la solución se
                escribe con prisa y la captura a veces llega después. */}
            {user.rol === 'admin' && editandoImagenes ? (
              <div style={{ marginTop: '14px' }}>
                <EditorImagenes
                  tipo="ticket"
                  id={ticket.id}
                  imagenes={ticket.imagenes_solucion}
                  etiqueta={t('imagenes.solucion')}
                  onCambio={(nuevas) => setTicket((t0) => ({ ...t0, imagenes_solucion: nuevas }))}
                />
                {ticket.indexado_kb && (
                  <div className="editor-imagenes-nota" style={{ marginTop: '-10px', marginBottom: '8px' }}>
                    {t('imagenes.tambien_en_kb')}
                  </div>
                )}
                <button type="button" className="boton-texto" onClick={() => setEditandoImagenes(false)}>
                  <X size={13} /> {t('imagenes.cerrar')}
                </button>
              </div>
            ) : (
              <>
                <GaleriaImagenes imagenes={ticket.imagenes_solucion} />
                {user.rol === 'admin' && (
                  <button type="button" className="boton-texto" style={{ marginTop: '8px' }}
                    onClick={() => setEditandoImagenes(true)}>
                    <Camera size={13} /> {t('imagenes.agregar')}
                  </button>
                )}
              </>
            )}
            {user.rol === 'admin' && !ticket.indexado_kb && ESTADOS_DE_CIERRE.includes(ticket.estado) && (
              <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)', marginTop: '10px' }}>
                {t('ticket.pendiente_indexar')}
              </div>
            )}

            {/* **La foto del problema ya está aquí arriba.** Si este defecto
                se reconoce mirándolo, documentarlo desde cero es volver a
                pedir un trabajo que ya se hizo: la descripción, la solución y
                las fotos están en este mismo ticket. Un clic las lleva a una
                ficha en borrador, donde alguien les pone título y las
                publica. */}
            {user.rol === 'admin' && ESTADOS_DE_CIERRE.includes(ticket.estado) && tieneFoto && (
              <div style={{ marginTop: '14px' }}>
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={crearFichaVisual}
                  disabled={creandoFicha}
                  style={{ padding: '9px 14px', fontSize: '0.85rem' }}
                >
                  <Camera size={15} />
                  {creandoFicha ? t('comun.cargando') : t('ticket.crear_ficha_visual')}
                </button>
                {avisoFicha && (
                  <div style={{
                    marginTop: '10px', fontSize: '0.85rem',
                    color: 'var(--peligro)', lineHeight: 1.5
                  }}>
                    {avisoFicha}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Cierre: la solución es obligatoria */}
      {estadoPendiente && (
        <CapaModal onCerrar={cancelarCierre}>
          <Formulario
            onClick={(e) => e.stopPropagation()}
            onSubmit={confirmarCierre}
            // Win+Shift+S y Ctrl+V sobre la solución: la captura se queda como
            // imagen; el texto se pega como siempre.
            onPaste={(e) => imagenesCierre.current?.pegar(e)}
            className="apple-card animate-fade-in"
            style={{ padding: '32px', maxWidth: '620px', width: '100%', maxHeight: '90vh', overflowY: 'auto' }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '16px', marginBottom: '8px' }}>
              <h2 style={{ fontSize: '1.35rem', fontWeight: '700', color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '10px' }}>
                <Wrench size={22} color="var(--accent-primary)" />
                {estadoPendiente === 'resuelto' ? t('ticket.cerrar_titulo_resuelto') : t('ticket.cerrar_titulo_cerrado')}
              </h2>
              <button
                type="button"
                onClick={cancelarCierre}
                className="btn-secondary"
                style={{ padding: '6px 10px' }}
                aria-label={t('ticket.cancelar')}
              >
                <X size={16} />
              </button>
            </div>

            <p style={{ color: 'var(--text-secondary)', fontSize: '0.95rem', marginBottom: '20px', lineHeight: '1.5' }}>
              {t('ticket.cerrar_ayuda')}
            </p>

            <div className="form-group">
              <label>{t('ticket.solucion')}</label>
              <textarea
                className="form-textarea"
                rows={6}
                autoFocus
                required
                minLength={SOLUCION_MIN_LONGITUD}
                placeholder={t('ticket.solucion_placeholder')}
                value={solucion}
                onChange={(e) => setSolucion(e.target.value)}
                style={{ fontSize: '1rem' }}
              />
              <div style={{
                fontSize: '0.85rem',
                marginTop: '8px',
                color: solucion.trim().length >= SOLUCION_MIN_LONGITUD ? 'var(--status-resuelto-text)' : 'var(--text-muted)'
              }}>
                {solucion.trim().length < SOLUCION_MIN_LONGITUD
                  ? t('ticket.solucion_faltan', { count: SOLUCION_MIN_LONGITUD - solucion.trim().length })
                  : t('ticket.solucion_ok')}
              </div>
            </div>

            <div className="form-group">
              <label>{t('ticket.descartado')}</label>
              <textarea
                className="form-textarea"
                rows={3}
                placeholder={t('ticket.descartado_placeholder')}
                value={descartado}
                onChange={(e) => setDescartado(e.target.value)}
                style={{ fontSize: '0.95rem' }}
              />
              <div style={{ fontSize: '0.83rem', marginTop: '8px', color: 'var(--text-muted)', lineHeight: 1.5 }}>
                {t('ticket.descartado_ayuda')}
              </div>
            </div>

            <EditorImagenes ref={imagenesCierre} tipo="ticket" etiqueta={t('imagenes.solucion')} />

            {errorCierre && (
              <div style={{
                background: 'var(--status-espera-proveedor-bg)',
                color: 'var(--status-espera-proveedor-text)',
                padding: '12px 16px',
                borderRadius: 'var(--radius-md)',
                fontSize: '0.9rem',
                marginBottom: '16px'
              }}>
                {errorCierre}
              </div>
            )}

            <div style={{ display: 'flex', gap: '12px', justifyContent: 'flex-end', marginTop: '24px', flexWrap: 'wrap' }}>
              <button type="button" onClick={cancelarCierre} className="btn-secondary" style={{ padding: '12px 22px' }}>
                {t('ticket.cancelar')}
              </button>
              <button
                type="submit"
                className="btn-primary"
                disabled={guardandoCierre || solucion.trim().length < SOLUCION_MIN_LONGITUD}
                style={{ padding: '12px 22px' }}
              >
                <CheckCircle size={18} />
                {guardandoCierre ? t('ticket.guardando') : t('ticket.confirmar_cierre')}
              </button>
            </div>
          </Formulario>
        </CapaModal>
      )}

      {/* Adjuntos. Sin nada que enseñar ni dónde subir —ticket cerrado y sin
          archivos— el componente no pinta nada, y la tarjeta que lo envuelve
          quedaba como un recuadro vacío entre la ficha y los comentarios. */}
      {(!soloLectura || (ticket.adjuntos || []).length > 0) && (
        <div className="apple-card" style={{ padding: '32px', marginBottom: '24px' }}>
          <AdjuntosTicket
            ticketId={ticket.id}
            adjuntos={ticket.adjuntos || []}
            onCambio={fetchTicket}
            puedeSubir={!soloLectura}
          />
        </div>
      )}

      {/* Comments Thread */}
      <div className="apple-card" style={{ padding: '32px' }}>
        <h2 style={{ fontSize: '1.35rem', fontWeight: '700', marginBottom: '24px', display: 'flex', alignItems: 'center', gap: '10px', color: 'var(--text-primary)' }}>
          <MessageSquare size={22} color="var(--accent-primary)" />
          {t('ticket.comentarios')}
        </h2>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px', marginBottom: '32px' }}>
          {ticket.comentarios && ticket.comentarios.length > 0 ? (
            ticket.comentarios.map((c) => (
              <div
                key={c.id}
                style={{
                  padding: '20px',
                  borderRadius: 'var(--radius-md)',
                  background: c.es_interno ? 'var(--status-espera-proveedor-bg)' : 'var(--bg-tertiary)',
                  border: c.es_interno ? '1px solid var(--status-espera-proveedor-bg)' : '1px solid transparent',
                  boxShadow: 'var(--shadow-sm)'
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                  <span style={{ fontWeight: '600', fontSize: '0.95rem', color: 'var(--text-primary)' }}>
                    {c.autor?.nombre}
                    {c.es_interno && (
                      <span style={{ marginLeft: '12px', fontSize: '0.75rem', color: 'var(--status-espera-proveedor-text)', background: 'var(--bg-secondary)', padding: '4px 8px', borderRadius: '6px', fontWeight: '600' }}>
                        {t('ticket.nota_interna')}
                      </span>
                    )}
                  </span>
                  <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                    {new Date(c.creado_en).toLocaleString(i18n.language)}
                  </span>
                </div>
                <div style={{ fontSize: '1rem', color: 'var(--text-primary)', lineHeight: '1.5' }}>
                  {c.comentario}
                </div>
              </div>
            ))
          ) : (
            <div style={{ color: 'var(--text-muted)', fontSize: '0.95rem', textAlign: 'center', padding: '20px' }}>
              {t('ticket.sin_comentarios')}
            </div>
          )}
        </div>

        {/* Add Comment Form */}
        {soloLectura ? (
          <div style={{
            display: 'flex', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between',
            gap: '12px', padding: '14px 16px', borderRadius: 'var(--radius-md)',
            background: 'var(--bg-tertiary)', color: 'var(--text-secondary)', fontSize: '0.92rem'
          }}>
            <span>{t('ticket.cerrado_solo_lectura')}</span>
            <button type="button" className="btn-secondary" onClick={() => navigate('/new-ticket')}>
              <Plus size={16} />
              {t('ticket.levantar_nuevo')}
            </button>
          </div>
        ) : (
        <Formulario onSubmit={handleAddComment}>
          <div className="form-group" style={{ marginBottom: '20px' }}>
            <textarea
              className="form-textarea"
              rows={3}
              placeholder={t('ticket.add_comment')}
              value={newComment}
              onChange={(e) => setNewComment(e.target.value)}
              required
              style={{ fontSize: '1rem' }}
            />
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            {user.rol === 'admin' ? (
              <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.95rem', color: 'var(--text-primary)', fontWeight: '500', cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={isInternal}
                  onChange={(e) => setIsInternal(e.target.checked)}
                  style={{ width: '18px', height: '18px', cursor: 'pointer' }}
                />
                {t('ticket.internal_note')}
              </label>
            ) : <div />}

            <button type="submit" className="btn-primary" disabled={submittingComment} style={{ height: '44px', padding: '0 24px' }}>
              <Send size={18} />
              {t('ticket.send_comment')}
            </button>
          </div>
        </Formulario>
        )}
      </div>
      {porCancelar && (
        <Confirmacion
          titulo={t('ticket.cancelar_titulo', { folio: ticket.folio })}
          mensaje={t('ticket.cancelar_confirmar')}
          textoConfirmar={t('ticket.cancelar_si')}
          /* No "Cancelar": en este diálogo esa palabra diría lo contrario. */
          textoCancelar={t('ticket.cancelar_no')}
          tono="peligro"
          onConfirmar={cancelarTicket}
          onCancelar={() => setPorCancelar(false)}
        />
      )}
    </div>
  );
};

export default TicketDetail;
