import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import api from '../api/client';
import { FileSignature, ArrowRight } from 'lucide-react';
import lista from '../lib/lista';

/**
 * Aviso de resguardos por firmar.
 *
 * Un resguardo sin firmar no sirve de constancia, así que no puede quedarse
 * esperando a que la persona entre por casualidad a su expediente. Se le avisa
 * donde sí entra todos los días.
 */
const AvisoResguardos = () => {
  const { t } = useTranslation();
  const [pendientes, setPendientes] = useState([]);

  useEffect(() => {
    let cancelado = false;
    api.get('/resguardos/mis-pendientes')
      .then((res) => { if (!cancelado) setPendientes(lista(res.data, 'los resguardos pendientes')); })
      // Si no se puede consultar, no se muestra nada: es un aviso, no un bloqueo.
      .catch(() => { if (!cancelado) setPendientes([]); });
    return () => { cancelado = true; };
  }, []);

  if (pendientes.length === 0) return null;

  return (
    <Link
      to="/expediente"
      className="animate-scale-in"
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: '14px',
        padding: '16px 20px',
        marginBottom: '20px',
        background: 'var(--status-espera-proveedor-bg)',
        color: 'var(--status-espera-proveedor-text)',
        borderRadius: 'var(--radius-md)',
        textDecoration: 'none',
        transition: 'transform 0.2s ease'
      }}
    >
      <FileSignature size={20} style={{ flexShrink: 0 }} />
      <div style={{ flex: 1 }}>
        <strong style={{ fontSize: '0.94rem' }}>
          {t('expediente.tiene_pendientes', { count: pendientes.length })}
        </strong>
        <div style={{ fontSize: '0.85rem', opacity: 0.9, marginTop: '2px' }}>
          {pendientes.map((r) => r.folio).join(' · ')}
        </div>
      </div>
      <ArrowRight size={18} style={{ flexShrink: 0 }} />
    </Link>
  );
};

export default AvisoResguardos;
