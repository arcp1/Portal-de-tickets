import React from 'react';
import { useTranslation } from 'react-i18next';
import { Clock, CheckCircle2, AlertCircle, RefreshCw, Truck } from 'lucide-react';

const StatusBadge = ({ estado }) => {
  const { t } = useTranslation();

  const getStatusConfig = (st) => {
    switch (st) {
      case 'abierto':
        return { label: t('dashboard.filter_abierto'), icon: AlertCircle, class: 'badge-abierto' };
      case 'en_proceso':
        return { label: t('dashboard.filter_en_proceso'), icon: RefreshCw, class: 'badge-en_proceso' };
      case 'espera_proveedor':
        return { label: t('dashboard.filter_espera_proveedor'), icon: Truck, class: 'badge-espera_proveedor' };
      case 'resuelto':
        return { label: t('dashboard.filter_resuelto'), icon: CheckCircle2, class: 'badge-resuelto' };
      case 'cerrado':
        return { label: t('dashboard.filter_cerrado'), icon: Clock, class: 'badge-cerrado' };
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
