import React from 'react';
import { useTranslation } from 'react-i18next';
import { Clock, CheckCircle2, AlertCircle, RefreshCw, Truck, XCircle } from 'lucide-react';

/* **El distintivo dice el estado de un ticket, no el nombre de un filtro.**

   Salía de `dashboard.filter_*`, que son los rótulos de la fila de filtros del
   tablero y por eso van en plural: un ticket suelto quedaba marcado
   "ABIERTOS", "RESUELTOS", "CERRADOS". Las etiquetas en singular ya existían
   —`ticket.estado_*`, las que usa el selector de la ficha—, así que el
   distintivo y el desplegable que lo cambia dicen ahora lo mismo. */
const StatusBadge = ({ estado }) => {
  const { t } = useTranslation();

  const getStatusConfig = (st) => {
    switch (st) {
      case 'abierto':
        return { label: t('ticket.estado_abierto'), icon: AlertCircle, class: 'badge-abierto' };
      case 'en_proceso':
        return { label: t('ticket.estado_en_proceso'), icon: RefreshCw, class: 'badge-en_proceso' };
      case 'espera_proveedor':
        return { label: t('ticket.estado_espera_proveedor'), icon: Truck, class: 'badge-espera_proveedor' };
      case 'resuelto':
        return { label: t('ticket.estado_resuelto'), icon: CheckCircle2, class: 'badge-resuelto' };
      case 'cerrado':
        return { label: t('ticket.estado_cerrado'), icon: Clock, class: 'badge-cerrado' };
      case 'cancelado':
        return { label: t('ticket.estado_cancelado'), icon: XCircle, class: 'badge-cancelado' };
      default:
        return { label: st, icon: Clock, class: 'badge-abierto' };
    }
  };

  const config = getStatusConfig(estado);
  const Icon = config.icon;

  return (
    <span className={`badge ${config.class}`}>
      <Icon size={12} />
      {config.label}
    </span>
  );
};

export default StatusBadge;
