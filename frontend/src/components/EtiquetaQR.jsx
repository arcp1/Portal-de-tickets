import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Printer, Download, Link2, X, QrCode } from 'lucide-react';
import api from '../api/client';
import CapaModal from './CapaModal';
import Aviso from './Aviso';
import { copiarTexto } from '../lib/portapapeles';
import { avisar, mensajeDeError } from '../lib/avisos';

/**
 * La etiqueta QR de un equipo, lista para imprimir y pegar.
 *
 * La imagen la dibuja el backend (backend/app/services/etiqueta_service.py):
 * así sale idéntica desde cualquier navegador y la impresora recibe un PNG a
 * 300 ppp, no una captura de pantalla. Aquí se pide con la sesión —un `<img>`
 * no puede mandar el token— y se enseña desde un `blob:`.
 *
 * **Imprimir** no abre otra ventana: se mete la imagen en la página con una
 * hoja `@page` de 4 × 2 pulgadas —la etiqueta de las Zebra de planta— y se
 * esconde todo lo demás solo mientras dura la impresión.
 */
export default function EtiquetaQR({ equipo, onCerrar }) {
  const { t } = useTranslation();
  const [url, setUrl] = useState(null);
  const [enlace, setEnlace] = useState('');
  const [aviso, setAviso] = useState('');

  useEffect(() => {
    let vivo = true;
    let creada = null;
    api.get(`/equipos/${equipo.id}/etiqueta.png`, { responseType: 'blob' })
      .then((res) => {
        if (!vivo) return;
        creada = URL.createObjectURL(res.data);
        setUrl(creada);
        setEnlace(res.headers?.['x-enlace-qr'] || '');
      })
      .catch((err) => { if (vivo) setAviso(mensajeDeError(err, t('qr.error'))); });
    return () => { vivo = false; if (creada) URL.revokeObjectURL(creada); };
  }, [equipo.id]);

  const nombreArchivo = `etiqueta-${equipo.id}-${(equipo.modelo || 'equipo')
    .replace(/[^A-Za-z0-9_-]+/g, '-')}.png`;

  const imprimir = () => {
    if (!url) return;
    const estilo = document.createElement('style');
    estilo.textContent = [
      '@page { size: 4in 2in; margin: 0; }',
      '@media print {',
      '  body > *:not(.impresion-etiqueta) { display: none !important; }',
      '  .impresion-etiqueta { display: block !important; }',
      '  .impresion-etiqueta img { width: 4in; height: 2in; display: block; }',
      '}',
    ].join('\n');
    const zona = document.createElement('div');
    zona.className = 'impresion-etiqueta';
    zona.style.display = 'none';
    const imagen = new Image();
    imagen.src = url;
    imagen.alt = '';
    zona.appendChild(imagen);
    document.head.appendChild(estilo);
    document.body.appendChild(zona);
    const limpiar = () => {
      estilo.remove();
      zona.remove();
      window.removeEventListener('afterprint', limpiar);
    };
    window.addEventListener('afterprint', limpiar);
    // Que la imagen esté decodificada antes de abrir el diálogo, o sale en blanco.
    (imagen.decode ? imagen.decode() : Promise.resolve())
      .catch(() => {})
      .finally(() => window.print());
  };

  const copiar = async () => {
    if (!enlace) return;
    const ok = await copiarTexto(enlace);
    avisar(t(ok ? 'qr.copiado' : 'qr.no_copiado'), { tono: ok ? 'exito' : 'atencion' });
  };

  const titulo = [equipo.marca, equipo.modelo].filter(Boolean).join(' ');

  return (
    <CapaModal onCerrar={onCerrar} etiqueta={t('qr.titulo')}>
      <div
        className="apple-card etiqueta-qr-dialogo"
        onClick={(e) => e.stopPropagation()}
      >
        <button type="button" onClick={onCerrar} className="dialogo-cerrar" aria-label={t('qr.cerrar')}>
          <X size={22} />
        </button>
        <h2 className="dialogo-titulo">
          <QrCode size={22} aria-hidden="true" /> {t('qr.titulo')}
        </h2>
        <p className="dialogo-sub">{titulo}{equipo.numero_serie ? ` · ${equipo.numero_serie}` : ''}</p>

        <Aviso texto={aviso} />

        <div className="etiqueta-qr-vista">
          {url
            ? <img src={url} alt={t('qr.alt', { equipo: titulo })} width={1200} height={600} />
            : !aviso && <div className="etiqueta-qr-cargando">{t('qr.generando')}</div>}
        </div>

        {enlace && (
          <p className="etiqueta-qr-enlace">
            <Link2 size={14} aria-hidden="true" />
            <code>{enlace}</code>
          </p>
        )}
        <p className="etiqueta-qr-pista">{t('qr.pista')}</p>

        <div className="etiqueta-qr-acciones">
          <button type="button" className="btn-primary" onClick={imprimir} disabled={!url}>
            <Printer size={17} /> {t('qr.imprimir')}
          </button>
          <a
            className={`btn-secondary${url ? '' : ' desactivado'}`}
            href={url || undefined}
            download={nombreArchivo}
            aria-disabled={!url}
          >
            <Download size={17} /> {t('qr.descargar')}
          </a>
          <button type="button" className="btn-secondary" onClick={copiar} disabled={!enlace}>
            <Link2 size={17} /> {t('qr.copiar')}
          </button>
        </div>
      </div>
    </CapaModal>
  );
}
