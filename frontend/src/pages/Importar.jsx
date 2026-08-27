import React, { useState, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import api from '../api/client';
import {
  Upload, Download, FileSpreadsheet, AlertTriangle, Check, X,
  KeyRound, ShieldCheck, ArrowRight
} from 'lucide-react';

/**
 * Importación masiva de personal.
 *
 * Dos pasos a propósito: primero se analiza el archivo y se muestra qué pasaría,
 * y solo entonces se importa. Nadie debería cargar 300 filas a ciegas.
 */
const Importar = () => {
  const { t } = useTranslation();

  const [archivo, setArchivo] = useState(null);
  const [analisis, setAnalisis] = useState(null);
  const [resultado, setResultado] = useState(null);
  const [modo, setModo] = useState('codigo');
  const [trabajando, setTrabajando] = useState(false);
  const [error, setError] = useState('');
  const entrada = useRef(null);

  const elegir = (f) => {
    setArchivo(f);
    setAnalisis(null);
    setResultado(null);
    setError('');
  };

  const analizar = async () => {
    if (!archivo) return;
    setTrabajando(true);
    setError('');
    try {
      const datos = new FormData();
      datos.append('archivo', archivo);
      const res = await api.post('/admin/importacion/analizar', datos, {
        headers: { 'Content-Type': 'multipart/form-data' }
      });
      setAnalisis(res.data);
      if (!res.data.ok) setError(res.data.error);
    } catch (err) {
      setError(err.response?.data?.detail || t('importar.error_analizar'));
    } finally {
      setTrabajando(false);
    }
  };

  const importar = async () => {
    setTrabajando(true);
    setError('');
    try {
      const datos = new FormData();
      datos.append('archivo', archivo);
      datos.append('modo_activacion', modo);
      const res = await api.post('/admin/importacion/importar', datos, {
        headers: { 'Content-Type': 'multipart/form-data' }
      });
      if (!res.data.importadas) {
        setError(res.data.error || t('importar.error_importar'));
      } else {
        setResultado(res.data);
        setAnalisis(null);
      }
    } catch (err) {
      setError(err.response?.data?.detail || t('importar.error_importar'));
    } finally {
      setTrabajando(false);
    }
  };

  const descargarPlantilla = async () => {
    const res = await api.get('/admin/importacion/plantilla', { responseType: 'blob' });
    descargar(res.data, 'plantilla-personal.csv');
  };

  const descargarCodigos = async () => {
    const res = await api.post('/admin/importacion/codigos-csv', resultado.filas,
      { responseType: 'blob' });
    descargar(res.data, 'codigos-activacion.csv');
  };

  const descargar = (blob, nombre) => {
    const url = URL.createObjectURL(blob);
    const enlace = document.createElement('a');
    enlace.href = url;
    enlace.download = nombre;
    enlace.click();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  };

  return (
    <div className="page-container animate-fade-in" style={{ maxWidth: '1000px' }}>
      <h1 style={{ fontSize: '1.85rem', fontWeight: '700', marginBottom: '6px', color: 'var(--text-primary)' }}>
        {t('importar.title')}
      </h1>
      <p style={{ color: 'var(--text-secondary)', marginBottom: '26px' }}>
        {t('importar.subtitle')}
      </p>

      {error && (
        <div className="animate-scale-in" style={{
          display: 'flex', alignItems: 'flex-start', gap: '10px',
          background: 'var(--status-espera-proveedor-bg)',
          color: 'var(--status-espera-proveedor-text)',
          padding: '14px 18px', borderRadius: 'var(--radius-md)',
          marginBottom: '18px', fontSize: '0.9rem', lineHeight: 1.5
        }}>
          <AlertTriangle size={18} style={{ flexShrink: 0, marginTop: '1px' }} /> {error}
        </div>
      )}

      {/* --- Resultado --- */}
      {resultado ? (
        <div className="apple-card animate-scale-in" style={{ padding: '30px' }}>
          <div style={{ textAlign: 'center', marginBottom: '24px' }}>
            <Check size={40} color="var(--status-resuelto-text)" style={{ margin: '0 auto 12px' }} />
            <h2 style={{ fontSize: '1.3rem', fontWeight: '700', color: 'var(--text-primary)' }}>
              {t('importar.listo', { n: resultado.importadas })}
            </h2>
          </div>

          {resultado.modo_activacion === 'codigo' ? (
            <div style={{
              background: 'var(--status-espera-proveedor-bg)',
              color: 'var(--status-espera-proveedor-text)',
              padding: '18px', borderRadius: 'var(--radius-md)',
              marginBottom: '20px', lineHeight: 1.55, fontSize: '0.9rem'
            }}>
              <strong>{t('importar.descargue_ahora')}</strong>
              <div style={{ marginTop: '6px' }}>{t('importar.codigos_unica_vez')}</div>
              <button onClick={descargarCodigos} className="btn-primary"
                style={{ padding: '11px 20px', marginTop: '14px' }}>
                <Download size={16} /> {t('importar.descargar_codigos')}
              </button>
            </div>
          ) : (
            <div style={{
              background: 'var(--bg-tertiary)', padding: '18px',
              borderRadius: 'var(--radius-md)', marginBottom: '20px',
              lineHeight: 1.55, fontSize: '0.9rem', color: 'var(--text-primary)'
            }}>
              <strong>{t('importar.sin_codigos_titulo')}</strong>
              <div style={{ marginTop: '6px', color: 'var(--text-secondary)' }}>
                {t('importar.sin_codigos_detalle')}
              </div>
            </div>
          )}

          <button onClick={() => { setResultado(null); setArchivo(null); }}
            className="btn-secondary" style={{ padding: '11px 20px' }}>
            {t('importar.importar_otro')}
          </button>
        </div>
      ) : (
        <>
          {/* --- Paso 1: archivo --- */}
          <div className="apple-card" style={{ padding: '26px', marginBottom: '20px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '14px', marginBottom: '18px', flexWrap: 'wrap' }}>
              <h2 style={{ fontSize: '1.05rem', fontWeight: '700', color: 'var(--text-primary)', margin: 0 }}>
                {t('importar.paso1')}
              </h2>
              <button onClick={descargarPlantilla} className="btn-secondary"
                style={{ padding: '9px 16px', fontSize: '0.86rem' }}>
                <Download size={15} /> {t('importar.plantilla')}
              </button>
            </div>

            <div
              onClick={() => entrada.current?.click()}
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => { e.preventDefault(); elegir(e.dataTransfer.files[0] || null); }}
              style={{
                padding: '30px', textAlign: 'center', cursor: 'pointer',
                border: `2px dashed ${archivo ? 'var(--accent-primary)' : 'var(--border-color)'}`,
                borderRadius: 'var(--radius-md)', transition: 'border-color 0.2s ease'
              }}>
              <input ref={entrada} type="file" accept=".csv,text/csv" style={{ display: 'none' }}
                onChange={(e) => elegir(e.target.files[0] || null)} />
              <FileSpreadsheet size={26} color={archivo ? 'var(--accent-primary)' : 'var(--text-muted)'} />
              <div style={{ fontSize: '0.95rem', color: 'var(--text-primary)', marginTop: '10px', fontWeight: archivo ? '600' : '400' }}>
                {archivo ? archivo.name : t('importar.elegir')}
              </div>
              <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: '5px' }}>
                {t('importar.columnas_minimas')}
              </div>
            </div>

            {archivo && !analisis && (
              <button onClick={analizar} disabled={trabajando} className="btn-primary"
                style={{ padding: '12px 22px', marginTop: '18px' }}>
                {trabajando ? t('importar.analizando') : (
                  <>{t('importar.analizar')} <ArrowRight size={16} /></>
                )}
              </button>
            )}
          </div>

          {/* --- Paso 2: vista previa --- */}
          {analisis && (
            <div className="apple-card animate-scale-in" style={{ padding: '26px' }}>
              <h2 style={{ fontSize: '1.05rem', fontWeight: '700', color: 'var(--text-primary)', marginBottom: '18px' }}>
                {t('importar.paso2')}
              </h2>

              <div style={{
                display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
                gap: '14px', marginBottom: '22px'
              }}>
                <Dato valor={analisis.total} etiqueta={t('importar.filas_leidas')} />
                <Dato valor={analisis.validas} etiqueta={t('importar.se_importaran')}
                  color="var(--status-resuelto-text)" />
                <Dato valor={analisis.con_error} etiqueta={t('importar.con_problema')}
                  color={analisis.con_error ? '#D8000C' : undefined} />
                <Dato valor={analisis.sin_correo} etiqueta={t('importar.sin_correo')} />
              </div>

              {analisis.con_error > 0 && (
                <div style={{ marginBottom: '22px' }}>
                  <h3 style={{ fontSize: '0.9rem', fontWeight: '600', color: '#D8000C', marginBottom: '10px' }}>
                    {t('importar.filas_con_problema')}
                  </h3>
                  <div style={{ maxHeight: '190px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    {analisis.filas.filter((f) => f.error).map((f) => (
                      <div key={f.fila} style={{
                        fontSize: '0.84rem', padding: '9px 12px',
                        background: '#FFF0F0', borderRadius: 'var(--radius-sm)', color: '#8B0000'
                      }}>
                        <strong>{t('importar.fila', { n: f.fila })}</strong> · {f.error}
                      </div>
                    ))}
                  </div>
                  <div style={{ fontSize: '0.83rem', color: 'var(--text-muted)', marginTop: '10px' }}>
                    {t('importar.nota_errores')}
                  </div>
                </div>
              )}

              {analisis.validas > 0 && (
                <>
                  <h3 style={{ fontSize: '0.9rem', fontWeight: '600', color: 'var(--text-primary)', marginBottom: '12px' }}>
                    {t('importar.como_activan')}
                  </h3>

                  <ModoOpcion
                    seleccionado={modo === 'codigo'} onClick={() => setModo('codigo')}
                    icono={<KeyRound size={18} />}
                    titulo={t('importar.modo_codigo')}
                    detalle={t('importar.modo_codigo_detalle')}
                  />
                  <ModoOpcion
                    seleccionado={modo === 'verificacion'} onClick={() => setModo('verificacion')}
                    icono={<ShieldCheck size={18} />}
                    titulo={t('importar.modo_verificacion')}
                    detalle={t('importar.modo_verificacion_detalle')}
                    aviso={analisis.sin_fecha_ingreso > 0
                      ? t('importar.faltan_fechas', { n: analisis.sin_fecha_ingreso })
                      : null}
                  />

                  <div style={{ display: 'flex', gap: '10px', marginTop: '22px', flexWrap: 'wrap' }}>
                    <button onClick={importar} disabled={trabajando} className="btn-primary"
                      style={{ padding: '12px 24px' }}>
                      <Upload size={16} />
                      {trabajando ? t('importar.importando') : t('importar.importar', { n: analisis.validas })}
                    </button>
                    <button onClick={() => { setAnalisis(null); setArchivo(null); }}
                      className="btn-secondary" style={{ padding: '12px 20px' }}>
                      <X size={16} /> {t('temas.cancelar')}
                    </button>
                  </div>
                </>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
};

const Dato = ({ valor, etiqueta, color }) => (
  <div style={{
    padding: '14px', background: 'var(--bg-tertiary)',
    borderRadius: 'var(--radius-md)', textAlign: 'center'
  }}>
    <div style={{ fontSize: '1.6rem', fontWeight: '700', color: color || 'var(--text-primary)' }}>
      {valor}
    </div>
    <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', marginTop: '2px' }}>
      {etiqueta}
    </div>
  </div>
);

const ModoOpcion = ({ seleccionado, onClick, icono, titulo, detalle, aviso }) => (
  <button type="button" onClick={onClick} style={{
    display: 'flex', gap: '14px', width: '100%', textAlign: 'left',
    padding: '16px 18px', marginBottom: '10px', cursor: 'pointer',
    background: seleccionado ? 'var(--bg-secondary)' : 'transparent',
    border: `2px solid ${seleccionado ? 'var(--accent-primary)' : 'var(--border-color)'}`,
    borderRadius: 'var(--radius-md)', transition: 'border-color 0.2s ease'
  }}>
    <div style={{ color: seleccionado ? 'var(--accent-primary)' : 'var(--text-muted)', flexShrink: 0, marginTop: '2px' }}>
      {icono}
    </div>
    <div>
      <div style={{ fontWeight: '600', color: 'var(--text-primary)', fontSize: '0.94rem' }}>{titulo}</div>
      <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: '3px', lineHeight: 1.5 }}>
        {detalle}
      </div>
      {aviso && (
        <div style={{ fontSize: '0.83rem', color: 'var(--status-espera-proveedor-text)', marginTop: '6px' }}>
          {aviso}
        </div>
      )}
    </div>
  </button>
);

export default Importar;
