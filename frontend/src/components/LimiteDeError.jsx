import React from 'react';
import { AlertTriangle, RotateCcw } from 'lucide-react';

/**
 * Atrapa los errores de render de React.
 *
 * Sin esto, cualquier excepción en un componente desmonta el árbol entero y el
 * usuario se queda con una pantalla en blanco, sin saber si el portal se cayó
 * o si su computadora se trabó. Con esto ve un mensaje y un botón.
 *
 * Tiene que ser una clase: React no expone `componentDidCatch` en hooks.
 */
class LimiteDeError extends React.Component {
  constructor(props) {
    super(props);
    this.state = { fallo: false, mensaje: '' };
  }

  static getDerivedStateFromError(error) {
    return { fallo: true, mensaje: error?.message || '' };
  }

  componentDidCatch(error, info) {
    // A la consola del navegador, que es donde lo va a buscar quien soporte
    // el portal. No se manda a ningún servicio externo: los datos de la planta
    // no salen de la planta.
    console.error('Error de render en el portal:', error, info?.componentStack);
  }

  render() {
    if (!this.state.fallo) return this.props.children;

    return (
      <div
        className="page-container animate-appear"
        style={{ maxWidth: '560px', paddingTop: '80px', textAlign: 'center' }}
      >
        <div className="apple-card" style={{ padding: '40px' }}>
          <AlertTriangle size={44} style={{ color: 'var(--status-espera-proveedor-text)', margin: '0 auto 20px' }} />
          <h1 style={{ fontSize: '1.35rem', fontWeight: '700', marginBottom: '10px', color: 'var(--text-primary)' }}>
            Algo se rompió en esta pantalla
          </h1>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.95rem', lineHeight: 1.55, marginBottom: '24px' }}>
            El portal sigue funcionando. Puede recargar y continuar; si vuelve a
            pasar, avise al equipo de TI mencionando qué estaba haciendo.
          </p>

          {this.state.mensaje && (
            <div style={{
              fontFamily: 'monospace',
              fontSize: '0.8rem',
              color: 'var(--text-muted)',
              background: 'var(--bg-tertiary)',
              padding: '12px 14px',
              borderRadius: 'var(--radius-md)',
              marginBottom: '24px',
              wordBreak: 'break-word',
              textAlign: 'left'
            }}>
              {this.state.mensaje}
            </div>
          )}

          <div style={{ display: 'flex', gap: '12px', justifyContent: 'center', flexWrap: 'wrap' }}>
            <button
              onClick={() => window.location.reload()}
              className="btn-primary"
              style={{ padding: '12px 22px' }}
            >
              <RotateCcw size={17} />
              Recargar
            </button>
            <button
              onClick={() => { window.location.href = '/'; }}
              className="btn-secondary"
              style={{ padding: '12px 22px' }}
            >
              Volver al inicio
            </button>
          </div>
        </div>
      </div>
    );
  }
}

export default LimiteDeError;
