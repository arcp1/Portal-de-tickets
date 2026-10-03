import React, { useState, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import api, { ESPERA_SUBIDA } from '../api/client';
import Selector from '../components/Selector';
import { usePlantas, SelectorPlanta } from '../lib/plantas';
import {
  Upload, Download, FileSpreadsheet, AlertTriangle, Check, X,
  KeyRound, ShieldCheck, ArrowRight, Columns3, Sparkles, Cake, CalendarDays, HardHat
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
  // En qué planta entran las personas importadas. Con una sola, esa.
  const [plantas] = usePlantas();
  const [plantaId, setPlantaId] = useState(null);
  const [analisis, setAnalisis] = useState(null);
  const [resultado, setResultado] = useState(null);
  const [modo, setModo] = useState('codigo');
  // Qué dato se le pedirá a la persona para activarse sola. El de nacimiento
  // por omisión: la fecha de ingreso no se la sabe medio mundo.
  const [datoVerificacion, setDatoVerificacion] = useState('numero_epp');
  // Mapeo de columnas cuando el archivo trae encabezados que no se reconocen.
  const [mapeo, setMapeo] = useState({});
  const [trabajando, setTrabajando] = useState(false);
  const [error, setError] = useState('');
  const entrada = useRef(null);

  const elegir = (f) => {
    setArchivo(f);
    setAnalisis(null);
    setResultado(null);
    setMapeo({});
    setError('');
  };

  const analizar = async (mapeoUsado = mapeo) => {
    if (!archivo) return;
    setTrabajando(true);
    setError('');
    try {
      const datos = new FormData();
      datos.append('archivo', archivo);
      if (plantaId) datos.append('sitio_id', String(plantaId));
      if (Object.keys(mapeoUsado).length) datos.append('mapeo', JSON.stringify(mapeoUsado));
      const res = await api.post('/admin/importacion/analizar', datos, {
        headers: { 'Content-Type': 'multipart/form-data' },
        timeout: ESPERA_SUBIDA
      });
      setAnalisis(res.data);
      // Si el modelo propuso un emparejamiento, se precarga para que el admin
      // solo confirme. Propone, no decide.
      if (res.data.necesita_mapeo && res.data.sugerencia) {
        setMapeo((previo) => ({ ...res.data.sugerencia, ...previo }));
      }
      if (!res.data.ok && !res.data.necesita_mapeo) setError(res.data.error);
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
      if (plantaId) datos.append('sitio_id', String(plantaId));
      datos.append('dato_verificacion', datoVerificacion);
      if (Object.keys(mapeo).length) datos.append('mapeo', JSON.stringify(mapeo));
      const res = await api.post('/admin/importacion/importar', datos, {
        headers: { 'Content-Type': 'multipart/form-data' },
        timeout: ESPERA_SUBIDA
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
    try {
      const res = await api.get('/admin/importacion/plantilla', { responseType: 'blob' });
      descargar(res.data, 'plantilla-personal.csv');
    } catch (err) {
      setError(err.response?.data?.detail || t('importar.error_descargar'));
    }
  };

  const descargarCodigos = async (area = null) => {
    try {
      const res = await api.post('/admin/importacion/codigos-csv', resultado.filas,
        { responseType: 'blob', params: area ? { area } : {} });
      descargar(res.data, area ? `codigos-${area}.csv` : 'codigos-activacion.csv');
    } catch (err) {
      // Estos codigos salen una sola vez: si la descarga falla hay que
      // enterarse en el momento, no al repartirlos.
      setError(err.response?.data?.detail || t('importar.error_descargar'));
    }
  };

  // Cuánta gente se quedaría sin poder activarse sola con el dato elegido.
  const faltantes = analisis
    ? ({
        numero_epp: analisis.sin_numero_epp,
        fecha_nacimiento: analisis.sin_fecha_nacimiento,
        fecha_ingreso: analisis.sin_fecha_ingreso
      }[datoVerificacion]) || 0
    : 0;

  // Las áreas del archivo, para que cada supervisor reparta lo suyo.
  const areasDelResultado = resultado
    ? [...new Set(resultado.filas.filter((f) => f.codigo && f.area).map((f) => f.area))].sort()
    : [];

  const descargar = (blob, nombre) => {
    const url = URL.createObjectURL(blob);
    const enlace = document.createElement('a');
    enlace.href = url;
    enlace.download = nombre;
    // Firefox ignora el click en un enlace que no esta en el documento.
    document.body.appendChild(enlace);
    enlace.click();
    document.body.removeChild(enlace);
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  };

  return (
    <div className="page-container animate-fade-in">
      <div className="page-header">
        <div>
          <h1 className="page-title">
            {t('importar.title')}
          </h1>
          <p>
              {t('importar.subtitle')}
          </p>
        </div>
      </div>

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
              {t('importar.listo', { count: resultado.importadas })}
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
              <button onClick={() => descargarCodigos()} className="btn-acento"
                style={{ padding: '11px 20px', marginTop: '14px' }}>
                <Download size={16} /> {t('importar.descargar_codigos')}
              </button>

              {areasDelResultado.length > 1 && (
                <div style={{ marginTop: '18px', paddingTop: '16px', borderTop: '1px solid var(--border-color)' }}>
                  <div style={{ fontWeight: 600, marginBottom: '4px' }}>
                    {t('importar.repartir_por_area')}
                  </div>
                  <div style={{ marginBottom: '10px' }}>{t('importar.repartir_detalle')}</div>
                  <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                    {areasDelResultado.map((area) => (
                      <button key={area} onClick={() => descargarCodigos(area)}
                        className="btn-secondary"
                        style={{ padding: '8px 14px', fontSize: '0.83rem' }}>
                        <Download size={14} /> {area}
                      </button>
                    ))}
                  </div>
                </div>
              )}
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
            {plantas.length > 1 && (
              <div className="form-group" style={{ maxWidth: '360px' }}>
                <label htmlFor="planta-importacion">{t('plantas.planta_importacion')}</label>
                <SelectorPlanta id="planta-importacion" plantas={plantas} value={plantaId}
                  onChange={setPlantaId} required />
              </div>
            )}
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

            {/* La flecha de `() => analizar()` no sobra: sin ella llega el
                evento del clic como si fuera el mapeo de columnas. */}
            {archivo && !analisis && (
              <button onClick={() => analizar()} disabled={trabajando} className="btn-acento"
                style={{ padding: '12px 22px', marginTop: '18px' }}>
                {trabajando ? t('importar.analizando') : (
                  <>{t('importar.analizar')} <ArrowRight size={16} /></>
                )}
              </button>
            )}
          </div>

          {/* --- Paso 1.5: decirle qué columna es cuál --- */}
          {analisis?.necesita_mapeo && (
            <MapeoColumnas
              analisis={analisis}
              mapeo={mapeo}
              onCambiar={(campo, encabezado) =>
                setMapeo((previo) => ({ ...previo, [campo]: encabezado }))}
              onConfirmar={() => analizar(mapeo)}
              trabajando={trabajando}
            />
          )}

          {/* --- Paso 2: vista previa --- */}
          {analisis && !analisis.necesita_mapeo && (
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
                  color={analisis.con_error ? 'var(--peligro)' : undefined} />
                <Dato valor={analisis.sin_correo} etiqueta={t('importar.sin_correo')} />
                <Dato valor={faltantes} etiqueta={t('importar.sin_fecha')}
                  color={faltantes ? 'var(--status-espera-proveedor-text)' : undefined} />
                <Dato valor={analisis.con_un_solo_factor || 0}
                  etiqueta={t('importar.un_solo_factor')}
                  color={analisis.con_un_solo_factor ? 'var(--status-espera-proveedor-text)' : undefined} />
              </div>

              {analisis.con_error > 0 && (
                <div style={{ marginBottom: '22px' }}>
                  <h3 style={{ fontSize: '0.9rem', fontWeight: '600', color: 'var(--peligro)', marginBottom: '10px' }}>
                    {t('importar.filas_con_problema')}
                  </h3>
                  <div style={{ maxHeight: '190px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    {analisis.filas.filter((f) => f.error).map((f) => (
                      <div key={f.fila} style={{
                        fontSize: '0.84rem', padding: '9px 12px',
                        background: 'var(--peligro-bg)', borderRadius: 'var(--radius-sm)', color: 'var(--peligro)'
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

              {/* **Las altas de administrador, a la vista.** La previa solo
                  listaba las filas con error, así que un archivo de RH con la
                  columna de perfil mal traída creaba administradores en
                  silencio: el resumen las contaba entre las "válidas" y nadie
                  las veía hasta que ya estaban dentro. Es la única fila del
                  archivo que reparte poder; merece su propio bloque. */}
              {(analisis.filas || []).some((f) => !f.error && f.rol === 'admin') && (
                <div style={{ marginBottom: '22px' }}>
                  <h3 style={{
                    fontSize: '0.9rem', fontWeight: '600',
                    color: 'var(--status-espera-proveedor-text)', marginBottom: '10px'
                  }}>
                    {t('importar.seran_admin')}
                  </h3>
                  <div style={{ maxHeight: '190px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    {analisis.filas.filter((f) => !f.error && f.rol === 'admin').map((f) => (
                      <div key={f.fila} style={{
                        fontSize: '0.84rem', padding: '9px 12px',
                        background: 'var(--status-espera-proveedor-bg)',
                        borderRadius: 'var(--radius-sm)',
                        color: 'var(--status-espera-proveedor-text)'
                      }}>
                        <strong>{t('importar.fila', { n: f.fila })}</strong> · {f.nombre}
                        {f.numero_empleado ? ` · ${f.numero_empleado}` : ''}
                      </div>
                    ))}
                  </div>
                  <div style={{ fontSize: '0.83rem', color: 'var(--text-muted)', marginTop: '10px' }}>
                    {t('importar.nota_admin')}
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
                    aviso={faltantes > 0
                      ? t('importar.faltan_fechas', { count: faltantes })
                      : null}
                  />

                  {modo === 'verificacion' && (
                    <div style={{
                      marginTop: '4px', marginBottom: '14px', paddingLeft: '14px',
                      borderLeft: '2px solid var(--border-color)'
                    }}>
                      <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', margin: '10px 0 8px' }}>
                        {t('importar.que_dato')}
                      </div>
                      <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                        <Pastilla
                          activa={datoVerificacion === 'numero_epp'}
                          onClick={() => setDatoVerificacion('numero_epp')}
                          icono={<HardHat size={14} />}
                          texto={t('importar.dato_epp')}
                          faltan={analisis.sin_numero_epp}
                        />
                        <Pastilla
                          activa={datoVerificacion === 'fecha_nacimiento'}
                          onClick={() => setDatoVerificacion('fecha_nacimiento')}
                          icono={<Cake size={14} />}
                          texto={t('importar.dato_nacimiento')}
                          faltan={analisis.sin_fecha_nacimiento}
                        />
                        <Pastilla
                          activa={datoVerificacion === 'fecha_ingreso'}
                          onClick={() => setDatoVerificacion('fecha_ingreso')}
                          icono={<CalendarDays size={14} />}
                          texto={t('importar.dato_ingreso')}
                          faltan={analisis.sin_fecha_ingreso}
                        />
                      </div>
                      <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: '9px', lineHeight: 1.5 }}>
                        {t('importar.por_que_nacimiento')}
                      </div>
                    </div>
                  )}

                  <div style={{ display: 'flex', gap: '10px', marginTop: '22px', flexWrap: 'wrap' }}>
                    <button onClick={importar} disabled={trabajando} className="btn-acento"
                      style={{ padding: '12px 24px' }}>
                      <Upload size={16} />
                      {trabajando ? t('importar.importando') : t('importar.importar', { count: analisis.validas })}
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

/**
 * Decirle al portal qué columna del archivo es cuál.
 *
 * Ninguna tabla de alias va a cubrir todo lo que RH escribe en un encabezado,
 * así que cuando no se reconoce se pregunta en vez de adivinar. Ollama propone
 * un emparejamiento si está disponible; **la decisión es de quien importa**, y
 * si el modelo no está, esta pantalla funciona igual.
 */
const MapeoColumnas = ({ analisis, mapeo, onCambiar, onConfirmar, trabajando }) => {
  const { t } = useTranslation();
  const campos = Object.entries(analisis.campos || {});
  const obligatorias = analisis.obligatorias || [];
  const detectadas = analisis.columnas_detectadas || {};

  const valorDe = (campo) => mapeo[campo] ?? detectadas[campo] ?? '';
  const completo = obligatorias.every((c) => valorDe(c));

  return (
    <div className="apple-card animate-scale-in" style={{ padding: '26px', marginBottom: '20px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '8px' }}>
        <Columns3 size={19} color="var(--accent-primary)" />
        <h2 style={{ fontSize: '1.05rem', fontWeight: '700', color: 'var(--text-primary)', margin: 0 }}>
          {t('importar.mapeo_titulo')}
        </h2>
      </div>
      <p style={{ color: 'var(--text-secondary)', fontSize: '0.88rem', marginBottom: '18px', lineHeight: 1.5 }}>
        {t('importar.mapeo_detalle')}
      </p>

      {analisis.sugerencia && (
        <div style={{
          display: 'flex', alignItems: 'flex-start', gap: '9px',
          background: 'var(--bg-tertiary)', padding: '12px 14px',
          borderRadius: 'var(--radius-md)', marginBottom: '18px',
          fontSize: '0.85rem', color: 'var(--text-secondary)', lineHeight: 1.5
        }}>
          <Sparkles size={16} style={{ flexShrink: 0, marginTop: '1px', color: 'var(--accent-primary)' }} />
          {t('importar.mapeo_sugerido')}
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(250px, 1fr))', gap: '14px' }}>
        {campos.map(([campo, descripcion]) => (
          <div key={campo} className="form-group" style={{ marginBottom: 0 }}>
            <label>
              {descripcion}
              {obligatorias.includes(campo) && (
                <span style={{ color: 'var(--peligro)', marginLeft: '4px' }}>*</span>
              )}
            </label>
            <Selector className="form-select" style={{ width: '100%' }}
              value={valorDe(campo)}
              onChange={(e) => onCambiar(campo, e.target.value)}>
              <option value="">{t('importar.mapeo_ninguna')}</option>
              {(analisis.encabezados || []).map((h) => (
                <option key={h} value={h}>{h}</option>
              ))}
            </Selector>
          </div>
        ))}
      </div>

      <button onClick={onConfirmar} disabled={!completo || trabajando}
        className="btn-acento" style={{ padding: '12px 22px', marginTop: '20px' }}>
        {trabajando ? t('importar.analizando') : (
          <>{t('importar.mapeo_confirmar')} <ArrowRight size={16} /></>
        )}
      </button>
      {!completo && (
        <div style={{ fontSize: '0.82rem', color: 'var(--text-muted)', marginTop: '9px' }}>
          {t('importar.mapeo_faltan')}
        </div>
      )}
    </div>
  );
};

const Pastilla = ({ activa, onClick, icono, texto, faltan }) => (
  <button type="button" onClick={onClick} style={{
    display: 'inline-flex', alignItems: 'center', gap: '7px',
    padding: '8px 14px', cursor: 'pointer', fontSize: '0.84rem',
    fontWeight: activa ? 600 : 500,
    borderRadius: 'var(--radius-full)',
    border: '1px solid ' + (activa ? 'var(--accent-primary)' : 'var(--border-color)'),
    background: activa ? 'var(--bg-tertiary)' : 'transparent',
    color: activa ? 'var(--accent-primary)' : 'var(--text-secondary)'
  }}>
    {icono} {texto}
    {faltan > 0 && (
      <span className="chip-dato" style={{ background: 'var(--status-espera-proveedor-bg)', color: 'var(--status-espera-proveedor-text)' }}>
        −{faltan}
      </span>
    )}
  </button>
);

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
