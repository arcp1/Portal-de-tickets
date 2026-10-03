import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import api from '../api/client';
import StatusBadge from '../components/StatusBadge';
import AvisoHorario, { EtiquetaSLA } from '../components/AvisoHorario';
import AvisoResguardos from '../components/AvisoResguardos';
import { EsqueletoLista } from '../components/Cargando';
import { Paperclip } from 'lucide-react';
import { Search, Filter, Plus, ChevronLeft, ChevronRight, MessageSquare, CheckCircle } from 'lucide-react';
import { useEventoPortal } from '../context/Eventos';
import { useAuth } from '../context/AuthContext';
import { texturaCritica, texturaAlta } from '../lib/tramado';
import { colorDeTicket } from '../lib/coloresTicket';
import Folio from '../components/Folio';
import EstadoVacio from '../components/EstadoVacio';
import Aviso from '../components/Aviso';
import lista from '../lib/lista';
import forma from '../lib/forma';
import { usePlantas, EtiquetaPlanta, SelectorPlanta } from '../lib/plantas';
import { FranjaAlertas } from '../components/CampanaAlertas';

// Tickets por página. El servidor acepta hasta 100; 20 es lo que cabe en una
// pantalla de planta sin volver la lista un muro.
const POR_PAGINA = 20;

// Un ticket abierto cuyo compromiso ya paso.
const estaVencido = (ticket) =>
  ticket.vence_en &&
  !['resuelto', 'cerrado', 'cancelado'].includes(ticket.estado) &&
  new Date(ticket.vence_en) < new Date();

/** Lo que puede cambiar de un ticket sin que cambie su identidad.
 *  Sirve para saber cuál se movió mientras mirabas la pantalla. */
const firmaTicket = (t) => [
  t.estado, t.prioridad, t.asignado_a, t.vence_en, t.solucion,
  (t.comentarios || []).length,
].join('|');

const Dashboard = () => {
  const { t, i18n } = useTranslation();
  const { user } = useAuth();
  // La marca de crítico es solo para quien atiende. A quien reporta no le
  // resuelve nada saber que su ticket es el más urgente de la cola —no puede
  // hacer nada con esa información— y en cambio convierte cada avería propia
  // en una alarma roja.
  const esAdmin = user?.rol === 'admin';
  // Se generan una vez para toda la lista, no una por tarjeta.
  const tramados = React.useMemo(() => (esAdmin
    ? { critica: texturaCritica(), alta: texturaAlta() }
    : {}), [esAdmin]);
  const navigate = useNavigate();

  const [tickets, setTickets] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filterStatus, setFilterStatus] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  // Lo que se le pide al servidor. `searchQuery` es lo que hay en la caja;
  // `busqueda`, lo que se manda cuando la persona deja de teclear.
  const [busqueda, setBusqueda] = useState('');
  const [pagina, setPagina] = useState(1);
  const [resumen, setResumen] = useState({ total: 0, paginas: 1 });
  // Los que acaban de moverse mientras mirabas. Se realzan un momento y se
  // olvidan: es una pista, no un estado del ticket.
  const [recienCambiados, setRecienCambiados] = useState(new Set());
  const [aviso, setAviso] = useState('');
  // TI es global: ve los tickets de todas las plantas y puede quedarse con
  // los de una. Con una sola planta el filtro no se enseña.
  const [plantas] = usePlantas();
  const [plantaFiltro, setPlantaFiltro] = useState(null);
  const variasPlantas = plantas.length > 1;

  // **La búsqueda va al servidor**, no filtra lo que ya llegó: con páginas, eso
  // solo buscaría en la visible y "no hay resultados" mentiría. Se espera a
  // que la persona deje de teclear para no mandar una petición por letra, y
  // se vuelve a la primera página: la cuarta de otra búsqueda no significa nada.
  useEffect(() => {
    const limpia = searchQuery.trim();
    if (limpia === busqueda) return undefined;
    const reloj = setTimeout(() => {
      setBusqueda(limpia);
      setPagina(1);
    }, 350);
    return () => clearTimeout(reloj);
  }, [searchQuery, busqueda]);

  useEffect(() => {
    fetchTickets();
  }, [filterStatus, busqueda, pagina, plantaFiltro]);

  /**
   * El tablero deja de ser una foto.
   *
   * Cuando alguien crea, mueve o comenta un ticket del sitio, el portal avisa
   * y la lista se vuelve a pedir. **Sin `setLoading`**: refrescar en silencio
   * es la diferencia entre "la pantalla se mantiene al día" y "la pantalla
   * parpadea cada vez que otro trabaja". El esqueleto de carga es para la
   * primera vez, no para esto.
   */
  useEventoPortal('tickets', () => refrescarEnSilencio());

  // **Solo cuenta la última petición.** Con clics rápidos en los filtros
  // —"Abiertos" y enseguida "Resueltos"— salían dos, y pintaba la que llegara
  // al final: con la red lenta de planta podía ser la de antes, y bajo el
  // filtro "Resueltos" quedaban los abiertos. El refresco automático corría
  // la misma suerte. Cada petición se numera y las que ya no son la última
  // se descartan al volver.
  const ultimaPeticion = useRef(0);

  const pedirTickets = async () => {
    const params = { pagina, por_pagina: POR_PAGINA };
    if (filterStatus) params.estado = filterStatus;
    if (busqueda) params.buscar = busqueda;
    if (esAdmin && plantaFiltro) params.sitio_id = plantaFiltro;
    const res = await api.get('/tickets', { params });
    // Un 200 con otra forma —la página de un proxy, un despliegue a medias—
    // se trata como el fallo que es, en vez de pintar un tablero vacío.
    if (!forma(res.data, ['items', 'total', 'paginas'], 'los tickets')) {
      throw new Error('Respuesta del listado con otra forma');
    }
    return res.data;
  };

  /** Lo que acompaña a cada página: cuántos hay y en cuántas páginas. */
  const aplicarResumen = (datos) => {
    setResumen({ total: datos.total, paginas: datos.paginas });
    // Si la página pedida ya no existe —se cerraron tickets mientras tanto—,
    // se va a la última que sí: quedarse en una vacía dice "no hay nada".
    if (datos.total > 0 && pagina > datos.paginas) setPagina(datos.paginas);
  };

  const irAPagina = (numero) => {
    setPagina(numero);
    window.scrollTo(0, 0);
  };

  const fetchTickets = async () => {
    const mia = ++ultimaPeticion.current;
    setLoading(true);
    try {
      const datos = await pedirTickets();
      if (mia !== ultimaPeticion.current) return;
      setTickets(lista(datos.items, 'los tickets'));
      aplicarResumen(datos);
      setAviso('');
    } catch (err) {
      // **El fallo tiene que verse.** Antes esto solo escribía en la consola,
      // así que si el backend no respondía la pantalla enseñaba el estado
      // vacío: "no hay tickets". En una pantalla que decide a qué avería va
      // alguien, esa frase no es un hueco de diseño, es una mentira — y la
      // única de las siete listas del portal que la decía.
      if (mia !== ultimaPeticion.current) return;
      setAviso(err.response?.data?.detail || t('dashboard.error_cargar'));
    } finally {
      if (mia === ultimaPeticion.current) setLoading(false);
    }
  };

  /** Igual, pero sin tocar el estado de carga ni avisar de un fallo.
   *  Si la red falla justo en un refresco automático, lo que hay en pantalla
   *  sigue siendo válido: no hay nada que decirle a nadie. */
  const refrescarEnSilencio = async () => {
    const mia = ++ultimaPeticion.current;
    try {
      // Por `lista` como la carga normal: un 200 con otro cuerpo reventaba el
      // `.filter` de abajo y se llevaba el tablero entero, sin catch que lo viera.
      // Se pide la misma página y el mismo filtro que se están mirando.
      const datos = await pedirTickets();
      if (mia !== ultimaPeticion.current) return;
      const nuevos = lista(datos.items, 'los tickets');
      aplicarResumen(datos);
      setTickets((previos) => {
        // Se marcan los que cambiaron, para realzarlos un momento.
        //
        // Comparar objetos no sirve —la respuesta trae objetos nuevos siempre,
        // así que marcaría todo— y **el modelo no tiene `updated_at`**, que
        // era lo primero que probé. Así que se compara una firma de los campos
        // que de verdad se mueven. Si algún día se añade una columna de
        // modificación, esto se sustituye por ella y queda más barato.
        const antes = new Map(previos.map((t) => [t.id, firmaTicket(t)]));
        setRecienCambiados(new Set(
          nuevos.filter((t) => antes.has(t.id) && antes.get(t.id) !== firmaTicket(t))
                .map((t) => t.id)
        ));
        return nuevos;
      });
    } catch { /* la pantalla actual sigue siendo válida */ }
  };

  return (
    <div className="page-container animate-fade-in">
      {/* Top Banner */}
      <div className="page-header">
        <div>
          <h1 className="page-title">{t('dashboard.title')}</h1>
          <p style={{ color: 'var(--text-secondary)', fontSize: '1rem', marginTop: '4px' }}>
            {t('dashboard.subtitle')}
          </p>
        </div>

        <button
          onClick={() => navigate('/new-ticket')}
          className="btn-primary"
        >
          <Plus size={18} />
          {t('nav.new_ticket')}
        </button>
      </div>

      {/* Controls Bar */}
      <div className="barra-herramientas">
        {/* Search Input */}
        <div style={{ position: 'relative', flex: '1', minWidth: '280px' }}>
          <Search size={18} style={{
            position: 'absolute',
            left: '14px',
            top: '50%',
            transform: 'translateY(-50%)',
            color: 'var(--text-muted)'
          }} />
          <input
            type="text"
            className="form-input"
            style={{ width: '100%', paddingLeft: '42px', height: '40px' }}
            placeholder={t('dashboard.search_placeholder')}
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
          <span className="pista-atajo" aria-hidden="true">/</span>
        </div>

        {esAdmin && variasPlantas && (
          <SelectorPlanta
            todas
            plantas={plantas}
            value={plantaFiltro}
            onChange={(v) => { setPlantaFiltro(v); setPagina(1); }}
            style={{ minWidth: '210px', height: '40px' }}
          />
        )}

        {/* Status Filters */}
        <div className="filtros-estado">
          <Filter size={16} style={{ color: 'var(--text-muted)' }} />
          {[
            { value: '', label: t('dashboard.filter_all') },
            { value: 'abierto', label: t('dashboard.filter_abierto') },
            { value: 'en_proceso', label: t('dashboard.filter_en_proceso') },
            { value: 'espera_proveedor', label: t('dashboard.filter_espera_proveedor') },
            { value: 'resuelto', label: t('dashboard.filter_resuelto') },
            { value: 'cerrado', label: t('dashboard.filter_cerrado') },
            { value: 'cancelado', label: t('dashboard.filter_cancelado') }
          ].map((st) => (
            <button
              key={st.value}
              onClick={() => { setFilterStatus(st.value); setPagina(1); }}
              className={`chip-filtro ${filterStatus === st.value ? 'chip-filtro--activo' : ''}`}
              aria-pressed={filterStatus === st.value}
            >
              {st.label}
            </button>
          ))}
        </div>
      </div>

      <Aviso texto={aviso} tono="peligro" />
      {esAdmin && <FranjaAlertas />}
      <AvisoResguardos />
      <AvisoHorario compacto />

      {/* Ticket List */}
      {loading ? (
        <EsqueletoLista filas={4} />
      ) : tickets.length === 0 ? (
        /* Dos vacíos distintos. Antes salían las dos frases a la vez —"no hay
           tickets registrados" y "no se encontraron con los filtros"—, así que
           con un filtro puesto se afirmaba que no había ninguno, y sin filtro
           se hablaba de filtros que no existían. */
        filterStatus || busqueda || plantaFiltro ? (
          <EstadoVacio
            icono={<Search size={26} />}
            texto={t('dashboard.sin_resultados')}
          />
        ) : (
          <EstadoVacio
            icono={<CheckCircle size={26} />}
            texto={t('dashboard.no_tickets')}
            detalle={t('dashboard.no_tickets_detalle')}
          />
        )
      ) : (
        <div className="lista-escalonada" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {tickets.map((ticket) => (
            <div
              key={ticket.id}
              className={[
                'apple-card',
                recienCambiados.has(ticket.id) ? 'realzar' : '',
                esAdmin && ticket.prioridad === 'critica' ? 'tarjeta-critica' : '',
                esAdmin && ticket.prioridad === 'alta' ? 'tarjeta-alta' : '',
                esAdmin && !['critica', 'alta'].includes(ticket.prioridad) ? 'tarjeta-prioridad' : '',
              ].filter(Boolean).join(' ')}
              onClick={() => navigate(`/tickets/${ticket.id}`, { viewTransition: true })}
              style={{
                // Crítica y alta llevan la textura entera de fondo; el resto
                // solo el color de su prioridad. Va por variable porque la
                // imagen se genera en tiempo de ejecución y una hoja de
                // estilos no puede conocerla.
                ...(esAdmin && tramados[ticket.prioridad]
                  ? { '--tramado': `url(${tramados[ticket.prioridad]})` }
                  : {}),
                ...(esAdmin && !['critica', 'alta'].includes(ticket.prioridad)
                  ? {
                      '--color-prioridad': colorDeTicket(ticket.prioridad).base,
                      '--fondo-prioridad': colorDeTicket(ticket.prioridad).fondo,
                    }
                  : {}),
                padding: '20px 24px',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: '20px',
                // Un vistazo basta para ver que se paso de tiempo.
                borderLeft: estaVencido(ticket) ? '3px solid var(--peligro)' : '3px solid transparent'
              }}
            >
              {/* La franja lleva la textura tramada; el aura la pone el CSS de
                  `.tarjeta-critica`. Va en un elemento propio porque los dos
                  pseudo-elementos de `.apple-card` ya están ocupados por el
                  filo iluminado y el reflejo. */}
              {esAdmin && ticket.prioridad === 'critica' && (
                <span className="aura-critica" aria-hidden="true" />
              )}

              <div style={{ flex: 1 }}>
                {/* `wrap`: en el teléfono las seis etiquetas no caben en una
                    línea, y sin partirse empujaban la lista 473 px a la derecha
                    del borde —medido a 360 px— con el folio aplastado en tres
                    renglones. */}
                <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: '8px 12px', marginBottom: '10px' }}>
                  {/* El color solo no basta: quien no distingue rojo de gris se
                      quedaria sin la senal entera. La palabra lo dice. */}
                  {esAdmin && ['critica', 'alta'].includes(ticket.prioridad) && (
                    <span
                      className="chip-critico"
                      style={{
                        color: colorDeTicket(ticket.prioridad).texto,
                        background: colorDeTicket(ticket.prioridad).fondo,
                        borderColor: colorDeTicket(ticket.prioridad).borde,
                      }}
                    >
                      {t(`ticket.${colorDeTicket(ticket.prioridad).etiqueta}`)}
                    </span>
                  )}
                  <Folio codigo={ticket.folio} />
                  {/* De qué planta: TI ve todas mezcladas, y quien trabaja
                      en varias también necesita saberlo. */}
                  {(esAdmin || variasPlantas) && <EtiquetaPlanta planta={ticket.sitio} compacta />}
                  <StatusBadge estado={ticket.estado} />
                  <EtiquetaSLA venceEn={ticket.vence_en} estado={ticket.estado} />
                  {(ticket.adjuntos || []).length > 0 && (
                    <span title={t('adjuntos.titulo')} style={{
                      display: 'inline-flex', alignItems: 'center', gap: '4px',
                      fontSize: '0.78rem', color: 'var(--text-muted)'
                    }}>
                      <Paperclip size={13} />{ticket.adjuntos.length}
                    </span>
                  )}
                  <span className="chip-dato" style={{
                    background: 'var(--bg-tertiary)',
                    color: 'var(--text-secondary)'
                  }}>
                    {/* La misma traducción que usa la ficha del ticket. Antes
                        salía el valor crudo de la base —"impresora",
                        "accesos"—, así que en inglés y en francés esta era la
                        única palabra en castellano de la tarjeta. */}
                    {t(`new_ticket.category_${ticket.categoria}`, { defaultValue: ticket.categoria })}
                  </span>
                  {/* Un cancelado no pasó por ningún canal: el "técnico" con el que
                      nace diría que alguien de TI lo resolvió. */}
                  {ticket.canal_resolucion && ticket.estado !== 'cancelado' && (
                    /* El fondo era `--status-abierto-bg`: un color de estado
                       prestado por una pastilla que no es un estado, sino un
                       dato. Se notaba al quitar la marca del panel —el resto
                       de la tarjeta en gris y esta en azul, sin que ese azul
                       dijera nada—. Ahora comparte superficie con la de
                       categoría y se distingue por el texto. */
                    <span className="chip-dato" style={{
                      background: 'var(--bg-tertiary)',
                      color: 'var(--accent-primary)'
                    }}>
                      {/* Etiqueta y valor traducidos: "Canal: tecnico" se
                          leía igual en los tres idiomas. */}
                      {t('dashboard.canal')}: {t(`metricas.canal_${ticket.canal_resolucion}`, { defaultValue: ticket.canal_resolucion })}
                    </span>
                  )}
                </div>

                <div style={{
                  fontSize: '1.1rem',
                  fontWeight: '600',
                  color: 'var(--text-primary)',
                  marginBottom: '8px'
                }}>
                  {ticket.descripcion_original}
                </div>

                <div style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '16px',
                  fontSize: '0.85rem',
                  color: 'var(--text-muted)'
                }}>
                  <span>{t('dashboard.reportado_por')} <strong style={{ color: 'var(--text-secondary)'}}>{ticket.usuario?.nombre}</strong></span>
                  <span>•</span>
                  <span>{new Date(ticket.creado_en).toLocaleString(i18n.language)}</span>
                  {ticket.comentarios && ticket.comentarios.length > 0 && (
                    <>
                      <span>•</span>
                      <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                        <MessageSquare size={14} />
                        {t('dashboard.comentarios', { count: ticket.comentarios.length })}
                      </span>
                    </>
                  )}
                </div>
              </div>

              <ChevronRight size={20} style={{ color: 'var(--text-muted)' }} />
            </div>
          ))}
        </div>
      )}

      {/* Al pie, y solo si hay algo que paginar. El total es el del filtro y
          la búsqueda puestos, no el de todo el tablero: es lo que responde
          "¿cuántos quedan de estos?". */}
      {!loading && resumen.total > 0 && (
        <nav className="paginacion" aria-label={t('dashboard.paginacion')}>
          <button type="button" className="btn-secondary"
            onClick={() => irAPagina(pagina - 1)} disabled={pagina <= 1}>
            <ChevronLeft size={16} /> {t('dashboard.anterior')}
          </button>
          <span className="paginacion-estado" aria-live="polite">
            {t('dashboard.pagina_de', { pagina, paginas: resumen.paginas })}
            {' · '}
            {t('dashboard.total_tickets', { count: resumen.total })}
          </span>
          <button type="button" className="btn-secondary"
            onClick={() => irAPagina(pagina + 1)} disabled={pagina >= resumen.paginas}>
            {t('dashboard.siguiente')} <ChevronRight size={16} />
          </button>
        </nav>
      )}
    </div>
  );
};

export default Dashboard;
