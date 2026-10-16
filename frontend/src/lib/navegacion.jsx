import React from 'react';
import {
  Ticket, PlusCircle, Laptop, Sliders, TrendingUp, ListChecks, Upload, Inbox,
  FileSignature, Users, BookOpen, Activity, BookOpenCheck, Brain, Images, Cpu, Factory,
  Bell, FolderOpen, FileText, ScrollText, Wallet
} from 'lucide-react';

/**
 * Las secciones del portal, en un solo sitio.
 *
 * **Por qué existe.** Esta lista la construía la barra dentro de su propio
 * render, y la paleta de comandos necesita exactamente la misma: las mismas
 * rutas, los mismos nombres traducidos y la misma diferencia entre lo que ve
 * un administrador y lo que ve un trabajador. Copiada en dos sitios, el día
 * que se añada una sección se añadirá en uno y no en el otro, y la paleta
 * dirá que no existe algo que sí está en la barra. Aquí se declara una vez.
 *
 * **Siete módulos, cada uno con sus pestañas** (reorganización del
 * 2026-10-05). Eran veinte pantallas repartidas en cuatro cajones con nombres
 * que no decían qué había dentro —Plantas vivía en «Sistema», la salud del
 * conocimiento también, y Temas mezclaba tres cosas—. Ahora la barra dice
 * *de qué* es cada cosa y las pestañas dentro de cada módulo dicen *qué* se
 * hace con ello. Las pestañas también salen de aquí (`modulosDe`): las pinta
 * `components/Modulo` encima de cada pantalla y la paleta las lista sueltas.
 */
export function modulosDe(t, esAdmin) {
  return {
    operacion: {
      texto: t('nav.grupo_operacion'),
      pestanas: [
        // Lo que el portal detectó solo: SLA, sensores, calificaciones bajas.
        { ruta: '/operacion/alertas', icono: <Bell size={16} />, texto: t('nav.alertas') },
        // Los sensores ESP32 de las plantas: temperatura, humedad, aire.
        { ruta: '/operacion/monitoreo', icono: <Cpu size={16} />, texto: t('nav.monitoreo') }
      ]
    },
    activos: {
      texto: t('nav.grupo_activos'),
      pestanas: esAdmin ? [
        { ruta: '/inventory', icono: <Laptop size={16} />, texto: t('nav.inventory') },
        { ruta: '/resguardos', icono: <FileSignature size={16} />, texto: t('nav.resguardos') },
        // Lo que cuestan los activos y el resto de TI (antes «Gastos TI», una
        // aplicación aparte). Aquí y no en Sistema: es dinero que se va en
        // equipos, licencias y servicios, y cada gasto se ata a un activo.
        { ruta: '/activos/gastos', icono: <Wallet size={16} />, texto: t('nav.gastos') }
      ] : [
        { ruta: '/inventory', icono: <Laptop size={16} />, texto: t('nav.inventory') }
      ]
    },
    personas: {
      texto: t('nav.usuarios'),
      pestanas: [
        // `/personas/:id` (el expediente de alguien) cae aquí: es la ruta
        // más larga que le queda por delante.
        { ruta: '/personas', icono: <Users size={16} />, texto: t('nav.usuarios') },
        // TI es global: las plantas se administran junto a la gente que las
        // trabaja, no entre los ajustes del sistema.
        { ruta: '/personas/plantas', icono: <Factory size={16} />, texto: t('nav.plantas') },
        { ruta: '/personas/importar', icono: <Upload size={16} />, texto: t('nav.importar') }
      ]
    },
    conocimiento: {
      texto: t('nav.grupo_conocimiento'),
      pestanas: [
        // Va primero: contesta «¿de qué sabe el portal y qué le falta?», que
        // es la pregunta anterior a escribir o corregir nada.
        { ruta: '/conocimiento', icono: <Brain size={16} />, texto: t('nav.salud') },
        { ruta: '/conocimiento/articulos', icono: <BookOpen size={16} />, texto: t('nav.articulos') },
        { ruta: '/conocimiento/procedimientos', icono: <BookOpenCheck size={16} />, texto: t('nav.soluciones') },
        { ruta: '/conocimiento/pasos', icono: <ListChecks size={16} />, texto: t('nav.pasos') },
        // Lo que no cabe en un texto: el defecto con su foto.
        { ruta: '/conocimiento/catalogo', icono: <Images size={16} />, texto: t('nav.catalogo_visual') },
        // Lo que espera a una persona: temas que el portal detectó y
        // borradores que escribió la máquina y nadie ha firmado.
        { ruta: '/conocimiento/bandeja', icono: <Inbox size={16} />, texto: t('nav.bandeja') }
      ]
    },
    documentos: {
      texto: t('nav.documentos'),
      // La planta solo ve los archivos que su carpeta le enseña; la
      // documentación técnica es de TI.
      pestanas: esAdmin ? [
        { ruta: '/documentos/archivos', icono: <FolderOpen size={16} />, texto: t('nav.archivos') },
        { ruta: '/documentos/tecnica', icono: <FileText size={16} />, texto: t('nav.documentacion') }
      ] : [
        { ruta: '/documentos/archivos', icono: <FolderOpen size={16} />, texto: t('nav.archivos') }
      ]
    },
    sistema: {
      texto: t('nav.grupo_sistema'),
      pestanas: [
        { ruta: '/sistema/metricas', icono: <TrendingUp size={16} />, texto: t('nav.metricas') },
        { ruta: '/sistema/reglas', icono: <Sliders size={16} />, texto: t('nav.rules') },
        { ruta: '/sistema/estado', icono: <Activity size={16} />, texto: t('nav.estado') },
        { ruta: '/sistema/bitacora', icono: <ScrollText size={16} />, texto: t('nav.bitacora') }
      ]
    }
  };
}

/**
 * La barra, en el orden del uso real: primero lo que hace todo el mundo
 * todos los días, al final lo de administración.
 *
 * Los módulos con pocas pestañas que se visitan juntas (Operación, Activos,
 * Sistema) son menús; los que tienen una pantalla de entrada clara (Personas,
 * Conocimiento, Documentos) son enlaces, y sus pestañas se ven al llegar.
 *
 * «Nuevo ticket» ya no está en la barra de TI: vive en el tablero, que es
 * donde se decide levantar uno. La planta lo conserva en la barra —es lo que
 * más hace—, y la ruta `/new-ticket` no cambia: los QR impresos apuntan ahí.
 */
export function seccionesDe(t, esAdmin) {
  const m = modulosDe(t, esAdmin);
  const tickets = {
    ruta: '/', icono: <Ticket size={18} />, texto: t('nav.dashboard'),
    // El detalle de un ticket y el formulario son parte del tablero.
    tambien: ['/tickets/', '/new-ticket']
  };
  return esAdmin ? [
    tickets,
    { clave: 'operacion', texto: m.operacion.texto, entradas: m.operacion.pestanas },
    { clave: 'activos', texto: m.activos.texto, entradas: m.activos.pestanas },
    { ruta: '/personas', icono: <Users size={18} />, texto: m.personas.texto, pestanas: m.personas.pestanas },
    { ruta: '/conocimiento', icono: <Brain size={18} />, texto: m.conocimiento.texto, pestanas: m.conocimiento.pestanas },
    { ruta: '/documentos/archivos', icono: <FolderOpen size={18} />, texto: m.documentos.texto, pestanas: m.documentos.pestanas },
    { clave: 'sistema', texto: m.sistema.texto, entradas: m.sistema.pestanas }
  ] : [
    { ...tickets, tambien: ['/tickets/'] },
    { ruta: '/new-ticket', icono: <PlusCircle size={18} />, texto: t('nav.new_ticket') },
    { ruta: '/inventory', icono: <Laptop size={18} />, texto: t('nav.inventory') },
    { ruta: '/documentos/archivos', icono: <FolderOpen size={18} />, texto: t('nav.documentos') }
  ];
}

/** ¿`a` es `ruta` o algo debajo de ella? Por segmentos: `/personas` no es
 *  prefijo de `/personasx`. */
export function estaDebajo(ruta, pathname) {
  if (ruta === '/') return pathname === '/';
  return pathname === ruta || pathname.startsWith(ruta.endsWith('/') ? ruta : ruta + '/');
}

/** La sección de la barra que corresponde a la ruta abierta. */
export function seccionActiva(seccion, pathname) {
  if (estaDebajo(seccion.ruta, pathname)) return true;
  if (seccion.pestanas?.some((p) => estaDebajo(p.ruta, pathname))) return true;
  return (seccion.tambien || []).some((r) => pathname === r || pathname.startsWith(r));
}

/** De las pestañas de un módulo, la que manda: la de la ruta más larga que
 *  queda por delante de la abierta. Así `/personas/12` es «Personas» y
 *  `/conocimiento/pasos` es «Pasos» y no «Salud». */
export function pestanaActiva(pestanas, pathname) {
  let mejor = null;
  for (const p of pestanas) {
    if (estaDebajo(p.ruta, pathname) && (!mejor || p.ruta.length > mejor.ruta.length)) mejor = p;
  }
  return mejor;
}

/** La misma lista sin cajones: cada sección con su ruta, su icono y, si venía
 *  dentro de un grupo o de un módulo con pestañas, su nombre como rastro para
 *  poder situarla. En la paleta se escribe «plantas», no «personas». */
export function aplanarSecciones(secciones) {
  const planas = [];
  for (const s of secciones) {
    const hijas = s.entradas || (s.pestanas?.length > 1 ? s.pestanas : null);
    if (hijas) {
      for (const e of hijas) planas.push({ ...e, grupo: s.texto });
    } else {
      planas.push(s);
    }
  }
  return planas;
}
