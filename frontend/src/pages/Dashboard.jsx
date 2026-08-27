import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import api from '../api/client';
import StatusBadge from '../components/StatusBadge';
import AvisoHorario, { EtiquetaSLA } from '../components/AvisoHorario';
import AvisoResguardos from '../components/AvisoResguardos';
import { EsqueletoLista } from '../components/Cargando';
import { Paperclip } from 'lucide-react';
import { Search, Filter, Plus, ChevronRight, MessageSquare, CheckCircle } from 'lucide-react';

// Un ticket abierto cuyo compromiso ya paso.
const estaVencido = (ticket) =>
  ticket.vence_en &&
  !['resuelto', 'cerrado'].includes(ticket.estado) &&
  new Date(ticket.vence_en) < new Date();

const Dashboard = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const [tickets, setTickets] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filterStatus, setFilterStatus] = useState('');
  const [searchQuery, setSearchQuery] = useState('');

  useEffect(() => {
    fetchTickets();
  }, [filterStatus]);

  const fetchTickets = async () => {
    setLoading(true);
    try {
      const url = filterStatus ? `/tickets?estado=${filterStatus}` : '/tickets';
      const res = await api.get(url);
      setTickets(res.data);
    } catch (err) {
      console.error("Error fetching tickets", err);
    } finally {
      setLoading(false);
    }
  };

  const filteredTickets = tickets.filter(t => {
    const q = searchQuery.toLowerCase();
    return t.folio.toLowerCase().includes(q) || t.descripcion_original.toLowerCase().includes(q);
  });

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
      <div className="apple-card" style={{
        padding: '16px 20px',
        marginBottom: '24px',
        display: 'flex',
        gap: '16px',
        flexWrap: 'wrap',
        alignItems: 'center',
        justifyContent: 'space-between'
      }}>
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
        </div>

        {/* Status Filters */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', overflowX: 'auto' }}>
          <Filter size={16} style={{ color: 'var(--text-muted)' }} />
          {[
            { value: '', label: t('dashboard.filter_all') },
            { value: 'abierto', label: t('dashboard.filter_abierto') },
            { value: 'en_proceso', label: t('dashboard.filter_en_proceso') },
            { value: 'espera_proveedor', label: t('dashboard.filter_espera_proveedor') },
            { value: 'resuelto', label: t('dashboard.filter_resuelto') },
            { value: 'cerrado', label: t('dashboard.filter_cerrado') }
          ].map((st) => (
            <button
              key={st.value}
              onClick={() => setFilterStatus(st.value)}
              style={{
                padding: '6px 14px',
                borderRadius: 'var(--radius-full)',
                fontSize: '0.85rem',
                fontWeight: '500',
                cursor: 'pointer',
                background: filterStatus === st.value ? 'var(--text-primary)' : 'var(--bg-tertiary)',
                color: filterStatus === st.value ? '#ffffff' : 'var(--text-secondary)',
                border: '1px solid transparent',
                transition: 'all 0.2s ease',
                whiteSpace: 'nowrap'
              }}
            >
              {st.label}
            </button>
          ))}
        </div>
      </div>

      <AvisoResguardos />
      <AvisoHorario compacto />

      {/* Ticket List */}
      {loading ? (
        <EsqueletoLista filas={4} />
      ) : filteredTickets.length === 0 ? (
        <div className="apple-card" style={{ textAlign: 'center', padding: '60px' }}>
          <CheckCircle size={48} style={{ color: 'var(--text-muted)', marginBottom: '16px', margin: '0 auto' }} />
          <h3 style={{ fontSize: '1.2rem', marginBottom: '8px', fontWeight: '600' }}>{t('dashboard.no_tickets')}</h3>
          <p style={{ color: 'var(--text-secondary)' }}>No se encontraron tickets con los filtros actuales.</p>
        </div>
      ) : (
        <div className="lista-escalonada" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {filteredTickets.map((ticket) => (
            <div
              key={ticket.id}
              className="apple-card"
              onClick={() => navigate(`/tickets/${ticket.id}`)}
              style={{
                padding: '20px 24px',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: '20px',
                // Un vistazo basta para ver que se paso de tiempo.
                borderLeft: estaVencido(ticket) ? '3px solid #D8000C' : '3px solid transparent'
              }}
            >
              <div style={{ flex: 1 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '10px' }}>
                  <span style={{
                    fontFamily: 'monospace',
                    fontWeight: '600',
                    color: 'var(--text-secondary)',
                    fontSize: '0.95rem',
                    background: 'var(--bg-tertiary)',
                    padding: '2px 8px',
                    borderRadius: '6px'
                  }}>
                    {ticket.folio}
                  </span>
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
                  <span style={{
                    fontSize: '0.8rem',
                    background: 'var(--bg-tertiary)',
                    padding: '2px 8px',
                    borderRadius: '6px',
                    color: 'var(--text-secondary)',
                    textTransform: 'capitalize',
                    fontWeight: '500'
                  }}>
                    {ticket.categoria}
                  </span>
                  {ticket.canal_resolucion && (
                    <span style={{
                      fontSize: '0.8rem',
                      background: '#E5F0FF',
                      color: 'var(--accent-primary)',
                      padding: '2px 8px',
                      borderRadius: '6px',
                      fontWeight: '500'
                    }}>
                      Canal: {ticket.canal_resolucion}
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
                  <span>Reportado por: <strong style={{ color: 'var(--text-secondary)'}}>{ticket.usuario?.nombre}</strong></span>
                  <span>•</span>
                  <span>{new Date(ticket.creado_en).toLocaleString()}</span>
                  {ticket.comentarios && ticket.comentarios.length > 0 && (
                    <>
                      <span>•</span>
                      <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                        <MessageSquare size={14} />
                        {ticket.comentarios.length} comentarios
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
    </div>
  );
};

export default Dashboard;
