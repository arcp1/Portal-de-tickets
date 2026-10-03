import React, { useState, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import api, { ESPERA_SUBIDA } from '../api/client';
import Confirmacion from './Confirmacion';
import ImagenApi from './ImagenApi';
import { Paperclip, Upload, Trash2, FileText, AlertTriangle } from 'lucide-react';

/**
 * Miniatura de un adjunto.
 *
 * La descarga autenticada vive en `ImagenApi`: el navegador no manda el token
 * en las peticiones de imagen, así que un `<img src="/api/...">` directo se
 * queda en un 401.
 */
const Miniatura = ({ ticketId, adjunto, alto = 84, ancho = 112 }) => (
  <ImagenApi
    ruta={`/tickets/${ticketId}/adjuntos/${adjunto.id}`}
    alt={adjunto.nombre_original}
    ancho={ancho}
    alto={alto}
  />
);

/**
 * Fotos y archivos del ticket.
 *
 * En planta una foto del error o del LED parpadeando ahorra media conversación.
 * Las imágenes se muestran en miniatura; lo demás como enlace.
 */
const AdjuntosTicket = ({ ticketId, adjuntos = [], onCambio, puedeSubir = true }) => {
  const { t } = useTranslation();
  const [subiendo, setSubiendo] = useState(false);
  const [error, setError] = useState('');
  const [arrastrando, setArrastrando] = useState(false);
  // El adjunto que espera el "¿seguro?". null = no hay pregunta abierta.
  const [porBorrar, setPorBorrar] = useState(null);
  const entrada = useRef(null);

  const subir = async (archivos) => {
    if (!archivos || archivos.length === 0) return;
    setSubiendo(true);
    setError('');
    // Arrastrar varios a la vez se salta el `accept` del selector. Si uno de
    // en medio era un .exe, los anteriores ya estaban subidos pero no se
    // pintaban hasta recargar, y el error no decía cuál de todos falló.
    let subidos = 0;
    let actual = null;
    try {
      for (const archivo of archivos) {
        actual = archivo;
        const datos = new FormData();
        datos.append('archivo', archivo);
        await api.post(`/tickets/${ticketId}/adjuntos`, datos, {
          headers: { 'Content-Type': 'multipart/form-data' },
          timeout: ESPERA_SUBIDA
        });
        subidos += 1;
      }
    } catch (err) {
      const motivo = err.response?.data?.detail || t('adjuntos.error_subir');
      setError(archivos.length > 1 && actual ? `${actual.name}: ${motivo}` : motivo);
    } finally {
      if (subidos > 0) onCambio?.();
      setSubiendo(false);
      if (entrada.current) entrada.current.value = '';
    }
  };

  const borrar = async (adjunto) => {
    setPorBorrar(null);
    try {
      await api.delete(`/tickets/${ticketId}/adjuntos/${adjunto.id}`);
      onCambio?.();
    } catch (err) {
      setError(err.response?.data?.detail || t('adjuntos.error_borrar'));
    }
  };

  // Sin archivos y sin poder subir —un ticket cerrado, visto por quien lo
  // reportó— no queda nada que enseñar: ni el título de una sección vacía.
  if (!puedeSubir && adjuntos.length === 0) return null;

  const esImagen = (tipo) => tipo.startsWith('image/');
  // Bajo un kilobyte se dice en bytes: una captura pequeña salía como "0 KB",
  // que parece un archivo vacío —y los vacíos el backend ya los rechaza—.
  const kb = (bytes) => bytes < 1024
    ? `${bytes} B`
    : bytes < 1024 * 1024
      ? `${Math.round(bytes / 1024)} KB`
      : `${(bytes / 1024 / 1024).toFixed(1)} MB`;

  /**
   * Abre el adjunto en una pestaña nueva.
   *
   * Igual que con las miniaturas, un enlace normal no lleva el token. Se
   * descarga autenticado y se abre desde un blob.
   */
  const abrir = async (adjunto) => {
    try {
      const res = await api.get(`/tickets/${ticketId}/adjuntos/${adjunto.id}`, { responseType: 'blob' });
      const objeto = URL.createObjectURL(res.data);
      window.open(objeto, '_blank', 'noopener,noreferrer');
      // Se libera después de que el navegador alcanzó a abrirlo.
      setTimeout(() => URL.revokeObjectURL(objeto), 60000);
    } catch (err) {
      setError(t('adjuntos.error_abrir'));
    }
  };

  return (
    <div>
      <h3 style={{
        fontSize: '1rem', fontWeight: '600', color: 'var(--text-primary)',
        marginBottom: '14px', display: 'flex', alignItems: 'center', gap: '8px'
      }}>
        <Paperclip size={18} color="var(--accent-primary)" />
        {t('adjuntos.titulo')}
        {adjuntos.length > 0 && (
          <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)', fontWeight: '500' }}>
            ({adjuntos.length})
          </span>
        )}
      </h3>

      {error && (
        <div className="animate-scale-in" style={{
          display: 'flex', alignItems: 'center', gap: '8px',
          background: 'var(--status-espera-proveedor-bg)',
          color: 'var(--status-espera-proveedor-text)',
          padding: '10px 14px', borderRadius: 'var(--radius-md)',
          fontSize: '0.86rem', marginBottom: '14px'
        }}>
          <AlertTriangle size={16} /> {error}
        </div>
      )}

      {adjuntos.length > 0 && (
        <div className="lista-escalonada" style={{
          display: 'flex', flexWrap: 'wrap', gap: '12px', marginBottom: '16px'
        }}>
          {adjuntos.map((a) => (
            <div key={a.id} style={{ position: 'relative' }}>
              <button
                type="button"
                onClick={() => abrir(a)}
                title={a.nombre_original}
                style={{
                  display: 'block',
                  width: '112px',
                  padding: 0,
                  cursor: 'pointer',
                  textAlign: 'left',
                  borderRadius: 'var(--radius-md)',
                  overflow: 'hidden',
                  border: '1px solid var(--border-color)',
                  background: 'var(--bg-secondary)'
                }}
              >
                {esImagen(a.tipo_mime) ? (
                  <Miniatura ticketId={ticketId} adjunto={a} />
                ) : (
                  <div style={{
                    width: '112px', height: '84px', display: 'flex',
                    alignItems: 'center', justifyContent: 'center',
                    background: 'var(--bg-tertiary)'
                  }}>
                    <FileText size={26} color="var(--text-secondary)" />
                  </div>
                )}
                {/* El nombre a la vista, no solo en el `title`: un PDF y un
                    .txt salían como dos mosaicos idénticos —mismo icono, solo
                    el tamaño— y en el celular no hay ratón que enseñe el
                    `title`. */}
                <div style={{
                  padding: '6px 8px', fontSize: '0.72rem', lineHeight: 1.35,
                  color: 'var(--text-secondary)'
                }}>
                  <div style={{
                    color: 'var(--text-primary)',
                    whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis'
                  }}>
                    {a.nombre_original}
                  </div>
                  {kb(a.tamano_bytes)}
                </div>
              </button>
              {puedeSubir && (
                <button
                  onClick={() => setPorBorrar(a)}
                  aria-label={t('adjuntos.borrar')}
                  style={{
                    position: 'absolute', top: '-6px', right: '-6px',
                    width: '24px', height: '24px', borderRadius: '50%',
                    border: 'none', cursor: 'pointer',
                    background: 'var(--peligro)', color: '#fff',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    boxShadow: 'var(--shadow-sm)'
                  }}
                >
                  <Trash2 size={12} />
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      {puedeSubir && (
        <div
          onDragOver={(e) => { e.preventDefault(); setArrastrando(true); }}
          onDragLeave={() => setArrastrando(false)}
          onDrop={(e) => {
            e.preventDefault();
            setArrastrando(false);
            subir(Array.from(e.dataTransfer.files));
          }}
          onClick={() => entrada.current?.click()}
          style={{
            padding: '20px',
            border: `2px dashed ${arrastrando ? 'var(--accent-primary)' : 'var(--border-color)'}`,
            borderRadius: 'var(--radius-md)',
            textAlign: 'center',
            cursor: subiendo ? 'wait' : 'pointer',
            background: arrastrando ? 'var(--bg-tertiary)' : 'transparent',
            transition: 'border-color 0.2s ease, background-color 0.2s ease'
          }}
        >
          <input
            ref={entrada}
            type="file"
            multiple
            accept="image/*,application/pdf,text/plain"
            style={{ display: 'none' }}
            onChange={(e) => subir(Array.from(e.target.files))}
          />
          {subiendo ? (
            <div style={{ maxWidth: '200px', margin: '0 auto' }}>
              <div className="progreso-indeterminado" />
              <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)', marginTop: '10px' }}>
                {t('adjuntos.subiendo')}
              </div>
            </div>
          ) : (
            <>
              <Upload size={22} color="var(--text-muted)" />
              <div style={{ fontSize: '0.88rem', color: 'var(--text-secondary)', marginTop: '8px' }}>
                {t('adjuntos.arrastra')}
              </div>
              <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginTop: '4px' }}>
                {t('adjuntos.formatos')}
              </div>
            </>
          )}
        </div>
      )}

      {porBorrar && (
        <Confirmacion
          titulo={t('adjuntos.borrar')}
          mensaje={t('adjuntos.confirmar_borrar')}
          textoConfirmar={t('comun.eliminar')}
          tono="peligro"
          onConfirmar={() => borrar(porBorrar)}
          onCancelar={() => setPorBorrar(null)}
        />
      )}
    </div>
  );
};

export default AdjuntosTicket;
