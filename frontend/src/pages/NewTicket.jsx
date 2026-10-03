import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import api from '../api/client';
import { useAuth } from '../context/AuthContext';
import SugerenciasKB from '../components/SugerenciasKB';
import AyudaVisual from '../components/AyudaVisual';
import RespuestaAsistente from '../components/RespuestaAsistente';
import AvisoHorario from '../components/AvisoHorario';
import Selector from '../components/Selector';
import Formulario from '../components/Formulario';
import Aviso from '../components/Aviso';
import {
  CheckCircle2, ArrowRight, ArrowLeft, Send, HelpCircle, AlertTriangle, QrCode
} from 'lucide-react';
import lista from '../lib/lista';
import { GaleriaImagenes } from '../components/ImagenesConocimiento';
import { avisar, mensajeDeError } from '../lib/avisos';
import useRetrasado from '../hooks/useRetrasado';
import { usePlantas, SelectorPlanta, EtiquetaPlanta } from '../lib/plantas';

// Las que TI puede revocar a quien abusa de ellas. Espejo de
// `PRIORIDADES_ALTAS` en backend/app/models: el backend las degrada a "media"
// igual, esto solo evita ofrecer lo que no se va a respetar.
const PRIORIDADES_ALTAS = ['alta', 'critica'];

// El mismo tope que el backend (`TEXTO_LARGO` en schemas/ticket.py).
const DESCRIPCION_MAXIMA = 5000;

/**
 * Clave de envío del formulario (`Idempotency-Key`, ver migración 0024).
 *
 * Con `getRandomValues` y no `randomUUID`: el portal se sirve por HTTP dentro
 * de la planta, y `randomUUID` solo existe en contextos seguros.
 */
const nuevaClaveDeEnvio = () => {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
};

/**
 * **El borrador sobrevive a lo que interrumpe.** Una sesión que caduca al
 * pulsar "Generar" mandaba al login con una recarga completa, y lo escrito se
 * perdía; lo mismo con una recarga sin querer. Va en `sessionStorage`: dura lo
 * que la pestaña —que es la misma del login— y no se queda en una computadora
 * compartida cuando se cierra. La clave de envío va con él: si el primer
 * intento sí se guardó, el reintento tras recargar no crea otro ticket.
 */
/** Las categorías de ticket; las mismas seis que valida el backend. */
const CATEGORIAS = ['impresora', 'red', 'equipo', 'software', 'accesos', 'otro'];

const claveDeBorrador = (usuarioId) => `portal_borrador_ticket_${usuarioId}`;

const leerBorrador = (usuarioId) => {
  try {
    const guardado = JSON.parse(sessionStorage.getItem(claveDeBorrador(usuarioId)) || 'null');
    return guardado && typeof guardado === 'object' ? guardado : null;
  } catch {
    return null;
  }
};

const NewTicket = () => {
  const { t } = useTranslation();
  const { user } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  // El chatbot manda aquí con la categoría ya clasificada y lo que el usuario
  // escribió. A partir de este punto es el flujo de siempre: el chat solo
  // sustituyó el paso de elegir categoría.
  const desdeChat = location.state || {};
  // **La etiqueta QR del equipo** manda aquí con `?equipo=<id>&categoria=<c>`
  // (ver backend/app/services/etiqueta_service.py). Es como el chat: ya se
  // sabe qué falla y en qué, así que se salta el paso de elegir categoría.
  // Del enlace solo se cree lo que se puede comprobar: la categoría tiene que
  // ser una de las seis y el equipo tiene que estar en la lista que el API da
  // a esta persona —que ya viene limitada a sus plantas—.
  const [desdeQR] = useState(() => {
    const consulta = new URLSearchParams(location.search);
    const categoria = consulta.get('categoria');
    const equipo = Number(consulta.get('equipo'));
    return {
      categoria: CATEGORIAS.includes(categoria) ? categoria : null,
      equipoId: Number.isInteger(equipo) && equipo > 0 ? String(equipo) : null,
    };
  });
  const categoriaDeAntemano = desdeChat.categoria || desdeQR.categoria;
  // Lo que el chat o el QR mandan manda más que un borrador viejo: es lo que
  // la persona acaba de hacer.
  const [borrador] = useState(() => (categoriaDeAntemano || desdeChat.descripcion || desdeQR.equipoId
    ? null : leerBorrador(user.id)));
  const claveEnvio = useRef(borrador?.claveEnvio || nuevaClaveDeEnvio());

  // Un borrador que ya pasó el checklist vuelve al detalle, no al principio.
  const [step, setStep] = useState(borrador?.categoria && borrador?.step === 3 ? 3 : 1);
  // **Sin categoría de antemano.** Venía puesta en "impresora", y quien no la
  // cambiaba —o no se fijaba— levantaba como falla de impresora lo que fuera:
  // se le hacía seguir los pasos de una impresora, el ticket caía en la regla
  // de impresoras y las métricas por categoría contaban mal. Si la clasificó
  // el chat, esa sí es un dato; si no, la elige la persona.
  const [categoria, setCategoria] = useState(categoriaDeAntemano || borrador?.categoria || '');
  const [checklists, setChecklists] = useState([]);
  const [checklistsCargados, setChecklistsCargados] = useState(false);
  const [checklistIndex, setChecklistIndex] = useState(0);
  const [resolvedByChecklist, setResolvedByChecklist] = useState(false);

  const [equipos, setEquipos] = useState([]);
  const [equipoId, setEquipoId] = useState(desdeQR.equipoId || borrador?.equipoId || '');
  // La planta del ticket. Solo se pregunta a quien tiene más de una (TI con
  // varias plantas, o una persona que trabaja en dos); el equipo, si se
  // elige, la decide.
  const [plantas] = usePlantas();
  const [plantaId, setPlantaId] = useState(borrador?.plantaId || user.sitio_id || null);
  const variasPlantas = plantas.length > 1;
  const [equiposCargados, setEquiposCargados] = useState(false);
  const [descripcion, setDescripcion] = useState(desdeChat.descripcion || borrador?.descripcion || '');
  const [prioridad, setPrioridad] = useState(borrador?.prioridad || 'media');
  // `!== false` y no `=== true`: una sesión guardada de antes de que existiera
  // el campo no lo trae, y ausente significa lo de siempre, permitido.
  const puedePedirAlta = user.rol === 'admin' || user.puede_usar_prioridad_alta !== false;
  const [submitting, setSubmitting] = useState(false);
  const enviando = useRef(false);
  // Lo que salio mal, dicho en la pantalla. Antes esto era un alert(): el
  // navegador congelaba el render mientras estuviera abierto y el texto salia
  // en español fijo, aunque la persona tuviera el portal en otro idioma.
  const [aviso, setAviso] = useState('');
  // El usuario marcó una sugerencia de la base de conocimiento como útil:
  // se resolvió solo, igual que con el checklist, y no se crea ticket.
  const [resolvedByKB, setResolvedByKB] = useState(false);
  // Lo mismo por el otro camino: reconoció su problema en una foto del
  // catálogo visual y la solución de esa ficha se lo arregló. Estado aparte y
  // no el mismo de arriba porque lo que se guarda en el ticket es distinto —el
  // canal es `visual`, no `kb`— y esa diferencia es toda la métrica de si
  // documentar con foto valió la pena.
  const [resolvedByVisual, setResolvedByVisual] = useState(false);

  useEffect(() => {
    if (categoria) fetchChecklists(categoria);
  }, [categoria]);

  useEffect(() => {
    try {
      if (!categoria && !descripcion.trim()) {
        sessionStorage.removeItem(claveDeBorrador(user.id));
        return;
      }
      sessionStorage.setItem(claveDeBorrador(user.id), JSON.stringify({
        categoria, descripcion, prioridad, equipoId, plantaId, step, claveEnvio: claveEnvio.current,
      }));
    } catch { /* sin almacenamiento: el formulario funciona igual, sin borrador */ }
  }, [categoria, descripcion, prioridad, equipoId, plantaId, step, user.id]);

  /** El formulario terminó en algo: el borrador ya no tiene nada que salvar. */
  const olvidarBorrador = () => {
    try { sessionStorage.removeItem(claveDeBorrador(user.id)); } catch { /* nada */ }
  };

  useEffect(() => {
    fetchEquipos();
  }, []);

  const fetchChecklists = async (cat) => {
    setChecklistsCargados(false);
    try {
      const res = await api.get(`/checklists?categoria=${cat}`);
      setChecklists(lista(res.data, 'los checklists'));
      setChecklistIndex(0);
      setResolvedByChecklist(false);
    } catch (err) {
      // Sin pasos se sigue al formulario, que es lo correcto: no hay que
      // impedirle a nadie levantar su ticket. Pero se dice, porque antes la
      // persona se saltaba el checklist sin saber que existía.
      avisar(mensajeDeError(err, t('new_ticket.error_checklist')), { tono: 'atencion' });
      setChecklists([]);
    } finally {
      setChecklistsCargados(true);
    }
  };

  // Si el chat ya clasificó la categoría, no se vuelve a preguntar: se entra
  // directo al checklist de esa categoría. Se espera a que carguen para no
  // saltárselo por llegar antes que la respuesta.
  const yaSaltamosLaCategoria = useRef(false);
  useEffect(() => {
    if (yaSaltamosLaCategoria.current) return;
    if (!categoriaDeAntemano || !checklistsCargados || step !== 1) return;
    yaSaltamosLaCategoria.current = true;
    setStep(checklists.length > 0 ? 2 : 3);
  }, [checklistsCargados, checklists, categoriaDeAntemano, step]);

  const fetchEquipos = async () => {
    try {
      const res = await api.get('/equipos');
      const recibidos = lista(res.data, 'los equipos');
      setEquipos(recibidos);
      // El equipo del QR tiene que ser uno que esta persona puede elegir.
      // Si no está —es de otra planta, o se dio de baja—, se dice y se sigue
      // sin él: el ticket se puede levantar igual.
      if (desdeQR.equipoId) {
        const delQR = recibidos.find((e) => String(e.id) === desdeQR.equipoId);
        if (delQR) {
          if (delQR.sitio?.id) setPlantaId(delQR.sitio.id);
        } else {
          setEquipoId('');
          avisar(t('qr.equipo_ajeno'), { tono: 'atencion', fija: true, clave: 'qr-equipo' });
        }
      }
    } catch (err) {
      // El campo de equipo es opcional: se avisa y se sigue sin él.
      avisar(mensajeDeError(err, t('new_ticket.error_equipos')), { tono: 'atencion' });
    } finally {
      setEquiposCargados(true);
    }
  };

  /** Elegir equipo fija la planta: un ticket va a la planta de su equipo. */
  const elegirEquipo = (id) => {
    setEquipoId(id);
    const eq = equipos.find((e) => String(e.id) === String(id));
    if (eq?.sitio?.id) setPlantaId(eq.sitio.id);
  };

  /** Cambiar de planta suelta el equipo si era de otra. */
  const elegirPlanta = (id) => {
    setPlantaId(id);
    const eq = equipos.find((e) => String(e.id) === String(equipoId));
    if (eq && eq.sitio?.id !== id) setEquipoId('');
  };

  const equiposDeLaPlanta = variasPlantas && plantaId
    ? equipos.filter((e) => !e.sitio || e.sitio.id === plantaId)
    : equipos;
  const equipoDelQR = desdeQR.equipoId && equiposCargados
    ? equipos.find((e) => String(e.id) === desdeQR.equipoId) : null;
  const plantaElegida = plantas.find((p) => p.id === plantaId);

  const handleNextStep = () => {
    if (step === 1) {
      if (checklists.length > 0) {
        setStep(2);
      } else {
        setStep(3);
      }
    }
  };

  /**
   * Registra una incidencia que el usuario resolvió solo.
   *
   * Se guarda como ticket ya resuelto con su canal. Sin este registro, una
   * incidencia deflectada no deja rastro y la tasa de deflección —la métrica
   * estrella— no se puede calcular. Si falla, no se le estorba al usuario:
   * ya resolvió su problema.
   */
  const registrarAutoResolucion = async (canal, solucion) => {
    try {
      await api.post('/tickets', {
        sitio_id: plantaId || null,
        categoria,
        descripcion_original: descripcion || t(`new_ticket.category_${categoria}`),
        prioridad: 'baja',
        equipo_id: equipoId ? parseInt(equipoId) : null,
        canal_auto_resolucion: canal,
        solucion,
        chat_sesion_id: desdeChat.sesionId || null
      }, { headers: { 'Idempotency-Key': claveEnvio.current } });
      olvidarBorrador();
    } catch (err) {
      console.error('No se pudo registrar la auto-resolución', err);
    }
  };

  // **Escribir no redibuja las tres ayudas en cada tecla.** Las sugerencias,
  // el asistente con su grafo y el reconocimiento visual ya esperan una pausa
  // antes de consultar; redibujarlas con cada letra solo cargaba el teclado
  // en las computadoras viejas. Reciben el texto cuando lleva un momento
  // quieto, y como son `memo` y sus avisos son estables, no se repintan entre
  // tanto. La referencia es para que esos avisos llamen siempre a la versión
  // de `registrarAutoResolucion` con los datos de ahora.
  const textoParaAyudas = useRetrasado(descripcion, 300);
  const registrarAhora = useRef(registrarAutoResolucion);
  registrarAhora.current = registrarAutoResolucion;
  const alResolverConFoto = useCallback((ficha) => {
    registrarAhora.current('visual', ficha.solucion);
    setResolvedByVisual(true);
  }, []);
  const alNoResolverConFoto = useCallback((ficha) => {
    // **Se deja dicho en la descripción, no en un campo oculto.** TI necesita
    // saber que esto ya se intentó —es media hora de técnico— y la persona
    // tiene que poder verlo y borrarlo si no le parece: es su reporte, no una
    // anotación del sistema a sus espaldas. Es lo mismo que hace el chat al
    // prellenar.
    const nota = t('visual.nota_no_arreglo', { titulo: ficha.titulo });
    setDescripcion((previa) =>
      previa.includes(nota) ? previa : `${previa.trim()}\n\n${nota}`);
  }, [t]);
  const alResolverConSugerencia = useCallback((sugerencia) => {
    registrarAhora.current('kb', sugerencia.contenido);
    setResolvedByKB(true);
  }, []);

  const handleChecklistAnswer = (resolved) => {
    if (resolved) {
      const paso = checklists[checklistIndex];
      const pregunta = paso.pregunta_texto || t(paso.pregunta_key, { defaultValue: paso.pregunta_key });
      registrarAutoResolucion(
        'checklist',
        `${t('new_ticket.resuelto_por_checklist')} ${pregunta}${paso.accion_si_no ? ` ${paso.accion_si_no}` : ''}`
      );
      setResolvedByChecklist(true);
    } else {
      if (checklistIndex + 1 < checklists.length) {
        setChecklistIndex(checklistIndex + 1);
      } else {
        setStep(3);
      }
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    // **El botón desactivado no basta.** `submitting` desactiva el botón
    // cuando React vuelve a pintar; dos envíos en el mismo instante —doble
    // Enter, doble toque en el móvil— salen antes de eso y crean dos tickets.
    // La referencia cambia en el acto.
    if (enviando.current) return;
    enviando.current = true;
    setSubmitting(true);
    setAviso('');
    try {
      const payload = {
        // Sin planta elegida decide el backend: la principal de la persona,
        // o la única que haya.
        sitio_id: plantaId || null,
        categoria: categoria,
        descripcion_original: descripcion,
        prioridad: prioridad,
        equipo_id: equipoId ? parseInt(equipoId) : null,
        // Enlaza la sesión del chatbot para poder medir su precisión.
        chat_sesion_id: desdeChat.sesionId || null
      };

      // La misma clave en cada intento: si un corte de red se comió la
      // respuesta del primero, el segundo recibe ese ticket y no crea otro.
      const res = await api.post('/tickets', payload, {
        headers: { 'Idempotency-Key': claveEnvio.current },
      });
      olvidarBorrador();
      navigate(`/tickets/${res.data.id}`);
    } catch (err) {
      setAviso(err.response?.data?.detail || t('new_ticket.error_crear'));
    } finally {
      enviando.current = false;
      setSubmitting(false);
    }
  };

  return (
    <div className="page-container page-container--estrecho animate-fade-in">
      <button
        onClick={() => navigate('/')}
        className="btn-secondary enlace-volver"
        style={{ marginBottom: '24px' }}
      >
        <ArrowLeft size={16} />
        {t('new_ticket.volver_tickets')}
      </button>

      <AvisoHorario />

      <div className="apple-card" style={{ padding: '40px' }}>
        <h1 className="page-title" style={{ marginBottom: '8px' }}>
          {t('new_ticket.title')}
        </h1>
        <p className="rotulo-seccion" style={{ marginBottom: '32px' }}>
          {step === 1 && t('new_ticket.step1_category')}
          {step === 2 && t('new_ticket.step2_checklist')}
          {step === 3 && t('new_ticket.step3_details')}
        </p>

        {/* Llegó escaneando la etiqueta: se le dice qué equipo está
            reportando, para que se dé cuenta si escaneó el de al lado. */}
        {equipoDelQR && (
          <div className="aviso-qr" role="status">
            <QrCode size={18} aria-hidden="true" />
            <span>
              {t('qr.reportando')}{' '}
              <strong>{[equipoDelQR.marca, equipoDelQR.modelo].filter(Boolean).join(' ')}</strong>
              {equipoDelQR.numero_serie ? ` · ${equipoDelQR.numero_serie}` : ''}
            </span>
            <EtiquetaPlanta planta={equipoDelQR.sitio} />
          </div>
        )}

        {/* STEP 1: Select Category */}
        {step === 1 && (
          <div className="animate-fade-in">
            <div className="form-group">
              <label>{t('ticket.categoria')}</label>
              <Selector
                className="form-select"
                value={categoria}
                onChange={(e) => setCategoria(e.target.value)}
                style={{ width: '100%' }}
              >
                <option value="" disabled>{t('new_ticket.elige_categoria')}</option>
                <option value="impresora">{t('new_ticket.category_impresora')}</option>
                <option value="red">{t('new_ticket.category_red')}</option>
                <option value="equipo">{t('new_ticket.category_equipo')}</option>
                <option value="software">{t('new_ticket.category_software')}</option>
                <option value="accesos">{t('new_ticket.category_accesos')}</option>
                <option value="otro">{t('new_ticket.category_otro')}</option>
              </Selector>
            </div>

            {/* Espera también a los pasos: con un clic rápido, "Continuar"
                llegaba antes que la respuesta, veía la lista vacía y se
                saltaba el checklist entero hasta el formulario. */}
            <button
              onClick={handleNextStep}
              disabled={!categoria || !checklistsCargados}
              className="btn-primary"
              style={{ marginTop: '24px', width: '100%', justifyContent: 'center', height: '48px', fontSize: '1rem' }}
            >
              {t('comun.continuar')}
              <ArrowRight size={18} />
            </button>
          </div>
        )}

        {/* STEP 2: Interactive Troubleshooting Checklist */}
        {step === 2 && (
          <div className="animate-fade-in">
            {resolvedByChecklist ? (
              <div style={{
                textAlign: 'center',
                padding: '40px',
                background: 'var(--status-resuelto-bg)',
                borderRadius: 'var(--radius-lg)'
              }}>
                <CheckCircle2 size={56} style={{ color: 'var(--status-resuelto-text)', marginBottom: '16px', margin: '0 auto' }} />
                <h2 style={{ fontSize: '1.35rem', marginBottom: '12px', fontWeight: '600', color: 'var(--text-primary)' }}>
                  {t('new_ticket.ticket_resolved_checklist')}
                </h2>
                <p style={{ color: 'var(--text-secondary)', marginBottom: '24px', fontSize: '0.95rem' }}>
                  {t('new_ticket.gracias_autoservicio', { planta: plantaElegida?.nombre || user.sitio_nombre || '' })}
                </p>
                <button onClick={() => navigate('/')} className="btn-primary" style={{ padding: '12px 24px' }}>
                  {t('new_ticket.finalizar_volver')}
                </button>
              </div>
            ) : checklists.length > 0 ? (
              <div style={{
                padding: '28px',
                background: 'var(--bg-tertiary)',
                borderRadius: 'var(--radius-lg)'
              }}>
                <div style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '10px',
                  marginBottom: '20px',
                  color: 'var(--accent-primary)'
                }}>
                  <HelpCircle size={22} />
                  <span style={{ fontWeight: '600', fontSize: '0.95rem' }}>
                    {t('new_ticket.pregunta_de', { n: checklistIndex + 1, total: checklists.length })}
                  </span>
                </div>

                <div style={{ fontSize: '1.15rem', fontWeight: '600', marginBottom: '16px', color: 'var(--text-primary)', lineHeight: '1.4' }}>
                  {checklists[checklistIndex].pregunta_texto
                    || t(checklists[checklistIndex].pregunta_key, { defaultValue: checklists[checklistIndex].pregunta_key })}
                </div>

                {checklists[checklistIndex].accion_si_no && (
                  <div style={{
                    padding: '16px',
                    background: 'var(--bg-secondary)',
                    borderRadius: 'var(--radius-md)',
                    fontSize: '0.9rem',
                    color: 'var(--text-secondary)',
                    marginBottom: '24px',
                    boxShadow: 'var(--shadow-sm)'
                  }}>
                    <strong style={{ color: 'var(--accent-primary)'}}>💡 {t('new_ticket.sugerencia')}</strong> {checklists[checklistIndex].accion_si_no}
                  </div>
                )}

                {/* Dónde está el botón, qué luz tiene que verse: el paso se
                    sigue mirando la foto en vez de buscando lo que dice el
                    texto. `key` para que al pasar al siguiente no se quede
                    abierto el visor del anterior. */}
                <GaleriaImagenes key={checklists[checklistIndex].id}
                  imagenes={checklists[checklistIndex].imagenes} />

                {/* Con `wrap`: a 360 px los dos botones juntos no caben —el
                    "No" lleva mayúsculas espaciadas— y la fila se salía 26 px
                    de la pantalla. Así, en un teléfono angosto quedan uno
                    encima del otro, cada uno a lo ancho. */}
                <div style={{ display: 'flex', gap: '12px 16px', marginTop: '24px', flexWrap: 'wrap' }}>
                  <button
                    onClick={() => handleChecklistAnswer(true)}
                    className="btn-secondary btn-secondary--exito"
                    style={{ flex: '1 1 150px', justifyContent: 'center' }}
                  >
                    {t('new_ticket.yes_resolved')}
                  </button>
                  <button
                    onClick={() => handleChecklistAnswer(false)}
                    className="btn-primary"
                    style={{ flex: '1 1 150px', justifyContent: 'center' }}
                  >
                    {t('new_ticket.no_continue')}
                  </button>
                </div>
              </div>
            ) : null}
          </div>
        )}

        {/* STEP 3: Create Ticket Form */}
        {step === 3 && (resolvedByKB || resolvedByVisual) && (
          <div
            className="animate-fade-in"
            style={{
              textAlign: 'center',
              padding: '40px',
              background: 'var(--status-resuelto-bg)',
              borderRadius: 'var(--radius-lg)'
            }}
          >
            <CheckCircle2 size={56} style={{ color: 'var(--status-resuelto-text)', marginBottom: '16px', margin: '0 auto' }} />
            <h2 style={{ fontSize: '1.35rem', marginBottom: '12px', fontWeight: '600', color: 'var(--text-primary)' }}>
              {t('kb.resuelto_titulo')}
            </h2>
            <p style={{ color: 'var(--text-secondary)', marginBottom: '24px', fontSize: '0.95rem' }}>
              {t('kb.resuelto_detalle')}
            </p>
            <div style={{ display: 'flex', gap: '12px', justifyContent: 'center', flexWrap: 'wrap' }}>
              <button onClick={() => navigate('/')} className="btn-primary" style={{ padding: '12px 24px' }}>
                {t('kb.finalizar')}
              </button>
              <button
                onClick={() => { setResolvedByKB(false); setResolvedByVisual(false); }}
                className="btn-secondary"
                style={{ padding: '12px 24px' }}
              >
                {t('kb.crear_de_todos_modos')}
              </button>
            </div>
          </div>
        )}

        {step === 3 && !resolvedByKB && !resolvedByVisual && (
          <Formulario onSubmit={handleSubmit} className="animate-fade-in">
            {variasPlantas && (
              <div className="form-group">
                <label htmlFor="planta-ticket">{t('plantas.planta')}</label>
                <SelectorPlanta
                  id="planta-ticket"
                  plantas={plantas}
                  value={plantaId}
                  onChange={elegirPlanta}
                  required
                />
              </div>
            )}

            <div className="form-group">
              <label>{t('ticket.equipo_asociado')}</label>
              <Selector
                className="form-select"
                value={equipoId}
                onChange={(e) => elegirEquipo(e.target.value)}
              >
                <option value="">-- {t('ticket.sin_equipo')} --</option>
                {equiposDeLaPlanta.map((eq) => (
                  <option key={eq.id} value={eq.id}>
                    {eq.tipo.toUpperCase()} - {eq.categoria} {eq.marca} {eq.modelo} ({eq.numero_serie || t('new_ticket.sin_serie')})
                  </option>
                ))}
              </Selector>
            </div>

            <div className="form-group">
              <label>{t('ticket.prioridad')}</label>
              <Selector
                className="form-select"
                value={prioridad}
                onChange={(e) => setPrioridad(e.target.value)}
              >
                <option value="baja">{t('ticket.prioridad_baja')}</option>
                <option value="media">{t('ticket.prioridad_media')}</option>
                {puedePedirAlta && (
                  <>
                    <option value="alta">{t('ticket.prioridad_alta')}</option>
                    <option value="critica">{t('ticket.prioridad_critica')}</option>
                  </>
                )}
              </Selector>
              {/* Se avisa al elegirla, no después: la sanción solo disuade si
                  se lee antes de pedir la prioridad, no en un correo de TI. */}
              {PRIORIDADES_ALTAS.includes(prioridad) && user.rol !== 'admin' && (
                <p className="aviso-campo" role="note">
                  <AlertTriangle size={15} aria-hidden="true" />
                  {t('new_ticket.aviso_prioridad_alta')}
                </p>
              )}
            </div>

            <div className="form-group">
              <label>{t('ticket.descripcion')}</label>
              <textarea
                className="form-textarea"
                rows={5}
                required
                placeholder={t('new_ticket.descripcion_placeholder')}
                value={descripcion}
                onChange={(e) => {
                  setDescripcion(e.target.value);
                  // El aviso hablaba del texto de antes: tras corregirlo
                  // seguía diciendo "al menos 3 caracteres" sobre uno de 6000.
                  if (aviso) setAviso('');
                }}
              />
              {/* Solo cerca del tope. Sin aviso, quien pegaba un correo
                  entero se enteraba al enviar. No se corta con `maxLength`:
                  el navegador recortaría el pegado en silencio. */}
              {descripcion.length > DESCRIPCION_MAXIMA * 0.8 && (
                <div className="rotulo-dato" style={{
                  textAlign: 'right', marginTop: '6px',
                  color: descripcion.length > DESCRIPCION_MAXIMA ? 'var(--peligro)' : 'var(--text-muted)',
                }}>
                  {descripcion.length} / {DESCRIPCION_MAXIMA}
                </div>
              )}
            </div>

            {/* **Primero las fotos.** Cuando lo que se describe es un
                defecto que se ve, tres sugerencias de texto sobre problemas
                que se describen igual no ayudan a distinguir nada; una foto
                sí. Si lo que se escribió no describe nada visible, o no hay
                foto de eso, este bloque no aparece y todo sigue igual. */}
            <AyudaVisual
              texto={textoParaAyudas}
              categoria={categoria}
              onResuelto={alResolverConFoto}
              onNoResolvio={alNoResolverConFoto}
            />

            {/* Incidencias parecidas ya resueltas. Si Ollama no está
                disponible este bloque simplemente no aparece. */}
            <SugerenciasKB
              texto={textoParaAyudas}
              categoria={categoria}
              sitioId={plantaId || user.sitio_id}
              onResuelto={alResolverConSugerencia}
            />

            {/* La respuesta redactada sobre lo que TI ya resolvió y escribió,
                con sus fuentes a la vista. Si de esto no hay nada en la planta,
                lo dice en vez de inventar. */}
            <RespuestaAsistente texto={textoParaAyudas} categoria={categoria} />

            {/* Pegado al boton, no al principio de la tarjeta: el formulario
                es largo y un aviso arriba se queda fuera de la vista, que es
                justo como se veia muerto el boton antes. */}
            <Aviso texto={aviso} />

            <button
              type="submit"
              className="btn-primary"
              disabled={submitting}
              style={{ width: '100%', justifyContent: 'center', marginTop: aviso ? '14px' : '32px', height: '48px', fontSize: '1rem' }}
            >
              {submitting ? t('new_ticket.generando') : (
                <>
                  <Send size={18} />
                  {t('new_ticket.submit_btn')}
                </>
              )}
            </button>
          </Formulario>
        )}
      </div>
    </div>
  );
};

export default NewTicket;
