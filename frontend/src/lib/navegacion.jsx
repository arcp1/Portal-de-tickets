import React from 'react';
import {
  Ticket, PlusCircle, Laptop, Sliders, TrendingUp, ListChecks,
  FileSignature, Users, BookOpen, Activity, BookOpenCheck, Brain, Images, Cpu, Factory
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
 * Devuelve la forma **agrupada**, que es la que necesita la barra —trece
 * secciones no caben en fila con su nombre—. La paleta la aplana con
 * `aplanarSecciones`, porque en una lista buscable un grupo no aporta nada:
 * se escribe el nombre de la sección, no el del cajón donde vive.
 */
export function seccionesDe(t, esAdmin) {
  // El orden es el del uso real: primero lo que hace todo el mundo todos los
  // días, al final lo de administración.
  return esAdmin ? [
    { ruta: '/', icono: <Ticket size={18} />, texto: t('nav.dashboard') },
    { ruta: '/new-ticket', icono: <PlusCircle size={18} />, texto: t('nav.new_ticket') },
    {
      clave: 'activos',
      texto: t('nav.grupo_activos'),
      entradas: [
        { ruta: '/inventory', icono: <Laptop size={16} />, texto: t('nav.inventory') },
        { ruta: '/resguardos', icono: <FileSignature size={16} />, texto: t('nav.resguardos') }
      ]
    },
    { ruta: '/usuarios', icono: <Users size={18} />, texto: t('nav.usuarios') },
    {
      clave: 'conocimiento',
      texto: t('nav.grupo_conocimiento'),
      entradas: [
        { ruta: '/temas', icono: <ListChecks size={16} />, texto: t('nav.temas') },
        { ruta: '/soluciones', icono: <BookOpenCheck size={16} />, texto: t('nav.soluciones') },
        { ruta: '/documentacion', icono: <BookOpen size={16} />, texto: t('nav.documentacion') },
        // Lo que no cabe en un texto: el defecto con su foto. Va en este
        // grupo y no en Sistema porque es conocimiento que alguien escribe,
        // no un ajuste que alguien calibra.
        { ruta: '/catalogo-visual', icono: <Images size={16} />, texto: t('nav.catalogo_visual') }
      ]
    },
    {
      clave: 'sistema',
      texto: t('nav.grupo_sistema'),
      entradas: [
        // Va primero del grupo: contesta '¿de que sabe el portal?', que es la
        // pregunta anterior a cualquier ajuste de reglas o de umbrales.
        { ruta: '/conciencia', icono: <Brain size={16} />, texto: t('nav.conciencia') },
        { ruta: '/rules', icono: <Sliders size={16} />, texto: t('nav.rules') },
        { ruta: '/metricas', icono: <TrendingUp size={16} />, texto: t('nav.metricas') },
        // Los sensores ESP32 de las plantas: temperatura, humedad, aire.
        { ruta: '/monitoreo', icono: <Cpu size={16} />, texto: t('nav.monitoreo') },
        // TI es global: las plantas se administran desde aquí.
        { ruta: '/plantas', icono: <Factory size={16} />, texto: t('nav.plantas') },
        { ruta: '/estado', icono: <Activity size={16} />, texto: t('nav.estado') }
      ]
    }
  ] : [
    { ruta: '/', icono: <Ticket size={18} />, texto: t('nav.dashboard') },
    { ruta: '/new-ticket', icono: <PlusCircle size={18} />, texto: t('nav.new_ticket') },
    { ruta: '/inventory', icono: <Laptop size={18} />, texto: t('nav.inventory') }
  ];
}

/** La misma lista sin cajones: cada sección con su ruta, su icono y, si venía
 *  dentro de un grupo, el nombre del grupo como rastro para poder situarla. */
export function aplanarSecciones(secciones) {
  const planas = [];
  for (const s of secciones) {
    if (s.entradas) {
      for (const e of s.entradas) planas.push({ ...e, grupo: s.texto });
    } else {
      planas.push(s);
    }
  }
  return planas;
}
