import React, { useState, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import api, { ESPERA_SUBIDA } from '../api/client';
import { Upload, X, Check, AlertTriangle, FileText } from 'lucide-react';
import CapaModal from './CapaModal';
import Selector from './Selector';
import Formulario from './Formulario';

const TIPOS = ['resguardo', 'responsiva', 'politica', 'contrato', 'identificacion', 'otro'];

/**
 * Alta de un documento en el expediente de una persona.
 *
 * El caso principal es el resguardo firmado a mano: se imprime, se firma en
 * papel, se escanea y se sube aquí. A partir de ese momento la persona lo tiene
 * disponible en su expediente sin tener que pedirlo.
 */
const SubirDocumento = ({ usuarioId, resguardos = [], onSubido, onCerrar }) => {
  const { t } = useTranslation();

  const [tipo, setTipo] = useState('resguardo');
  const [titulo, setTitulo] = useState('');
  const [descripcion, setDescripcion] = useState('');
  const [resguardoId, setResguardoId] = useState('');
  const [vigenteHasta, setVigenteHasta] = useState('');
  const [archivo, setArchivo] = useState(null);
  const [enviando, setEnviando] = useState(false);
  const [error, setError] = useState('');
  const entrada = useRef(null);

  const valido = archivo && titulo.trim().length >= 4;

  const enviar = async (e) => {
    e.preventDefault();
    if (!valido) return;
    setEnviando(true);
    setError('');
    try {
      const datos = new FormData();
      datos.append('usuario_id', String(usuarioId));
      datos.append('tipo', tipo);
      datos.append('titulo', titulo.trim());
      if (descripcion.trim()) datos.append('descripcion', descripcion.trim());
      if (resguardoId) datos.append('resguardo_id', resguardoId);
      if (vigenteHasta) datos.append('vigente_hasta', new Date(vigenteHasta).toISOString());
      datos.append('archivo', archivo);

      await api.post('/documentos', datos, {
        headers: { 'Content-Type': 'multipart/form-data' },
        timeout: ESPERA_SUBIDA
      });
      onSubido?.();
    } catch (err) {
      setError(err.response?.data?.detail || t('expediente.error_subir'));
      setEnviando(false);
    }
  };

  // Al elegir un resguardo, el título se propone solo.
  const elegirResguardo = (id) => {
    setResguardoId(id);
    const r = resguardos.find((x) => String(x.id) === String(id));
    if (r && !titulo.trim()) {
      setTitulo(t('expediente.titulo_resguardo_firmado', { folio: r.folio }));
    }
  };

  return (
    <CapaModal onCerrar={onCerrar}>
      <Formulario onClick={(e) => e.stopPropagation()} onSubmit={enviar}
        className="apple-card animate-scale-in"
        style={{ padding: '30px', maxWidth: '580px', width: '100%', maxHeight: '92vh', overflowY: 'auto' }}>

        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '16px', marginBottom: '18px' }}>
          <h2 style={{ fontSize: '1.2rem', fontWeight: '700', color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '10px' }}>
            <FileText size={20} color="var(--accent-primary)" />
            {t('expediente.subir_titulo')}
          </h2>
          <button type="button" onClick={onCerrar} className="btn-secondary" style={{ padding: '6px 10px' }}>
            <X size={16} />
          </button>
        </div>

        <div className="form-group">
          <label>{t('expediente.tipo_documento')}</label>
          <Selector className="form-select" value={tipo} onChange={(e) => setTipo(e.target.value)}>
            {TIPOS.map((x) => <option key={x} value={x}>{t(`expediente.tipo_${x}`)}</option>)}
          </Selector>
        </div>

        {/* Un resguardo escaneado se liga a su registro en el portal. */}
        {tipo === 'resguardo' && resguardos.length > 0 && (
          <div className="form-group">
            <label>{t('expediente.ligar_resguardo')}</label>
            <Selector className="form-select" value={resguardoId}
              onChange={(e) => elegirResguardo(e.target.value)}>
              <option value="">{t('expediente.sin_ligar')}</option>
              {resguardos.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.folio} · {r.equipo ? `${r.equipo.marca} ${r.equipo.modelo}` : '—'}
                </option>
              ))}
            </Selector>
          </div>
        )}

        <div className="form-group">
          <label>{t('expediente.titulo_documento')}</label>
          <input className="form-input" required style={{ width: '100%' }} value={titulo}
            placeholder={t('expediente.titulo_ejemplo')}
            onChange={(e) => setTitulo(e.target.value)} />
        </div>

        <div className="form-group">
          <label>{t('expediente.descripcion')}</label>
          <textarea className="form-textarea" rows={2} value={descripcion}
            onChange={(e) => setDescripcion(e.target.value)} />
        </div>

        <div className="form-group">
          <label>{t('expediente.vigencia')}</label>
          <input type="date" className="form-input" style={{ width: '100%' }}
            value={vigenteHasta} onChange={(e) => setVigenteHasta(e.target.value)} />
          <div style={{ fontSize: '0.79rem', color: 'var(--text-muted)', marginTop: '5px' }}>
            {t('expediente.vigencia_nota')}
          </div>
        </div>

        <div
          onClick={() => entrada.current?.click()}
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => { e.preventDefault(); setArchivo(e.dataTransfer.files[0] || null); }}
          style={{
            padding: '22px', border: `2px dashed ${archivo ? 'var(--accent-primary)' : 'var(--border-color)'}`,
            borderRadius: 'var(--radius-md)', textAlign: 'center', cursor: 'pointer',
            marginBottom: '20px', transition: 'border-color 0.2s ease'
          }}>
          <input ref={entrada} type="file" accept="application/pdf,image/*"
            style={{ display: 'none' }}
            onChange={(e) => setArchivo(e.target.files[0] || null)} />
          <Upload size={22} color={archivo ? 'var(--accent-primary)' : 'var(--text-muted)'} />
          <div style={{ fontSize: '0.9rem', color: 'var(--text-primary)', marginTop: '8px', fontWeight: archivo ? '600' : '400' }}>
            {archivo ? archivo.name : t('expediente.elegir_archivo')}
          </div>
          <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginTop: '4px' }}>
            {t('expediente.formatos')}
          </div>
        </div>

        {/* Junto a los botones: el diálogo tiene scroll y arriba, bajo el
            título, el error de un archivo rechazado quedaba fuera de la vista
            de quien acababa de pulsar Subir. */}
        {error && (
          <div className="animate-scale-in" style={{
            display: 'flex', alignItems: 'center', gap: '8px',
            background: 'var(--status-espera-proveedor-bg)',
            color: 'var(--status-espera-proveedor-text)',
            padding: '12px 14px', borderRadius: 'var(--radius-md)',
            fontSize: '0.87rem', marginBottom: '16px'
          }}>
            <AlertTriangle size={16} /> {error}
          </div>
        )}

        <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
          <button type="button" onClick={onCerrar} className="btn-secondary" style={{ padding: '11px 20px' }}>
            {t('temas.cancelar')}
          </button>
          <button type="submit" className="btn-primary" disabled={!valido || enviando}
            style={{ padding: '11px 20px' }}>
            <Check size={16} /> {enviando ? t('adjuntos.subiendo') : t('expediente.subir')}
          </button>
        </div>
      </Formulario>
    </CapaModal>
  );
};

export default SubirDocumento;
