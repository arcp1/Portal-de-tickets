from fastapi import APIRouter
from app.api.auth import router as auth_router
from app.api.tickets import router as tickets_router
from app.api.equipos import router as equipos_router
from app.api.checklists import router as checklists_router
from app.api.reglas import router as reglas_router
from app.api.sitios import router as sitios_router
from app.api.kb import router as kb_router
from app.api.chat import router as chat_router
from app.api.metricas import router as metricas_router
from app.api.eventos import router as eventos_router
from app.api.conciencia import router as conciencia_router, admin_router as conciencia_admin_router
from app.api.temas import router as temas_router
from app.api.adjuntos import router as adjuntos_router
from app.api.estado import admin_router as estado_admin_router
from app.api.estado import router as estado_router
from app.api.asistente import router as asistente_router
from app.api.auditoria import router as auditoria_router
from app.api.soluciones import router as soluciones_router
from app.api.resguardos import router as resguardos_router, expediente_router
from app.api.documentos import router as documentos_router
from app.api.cuentas import publico_router as cuentas_publico_router, admin_router as cuentas_admin_router
from app.api.documentacion_ti import router as documentacion_router
from app.api.importacion import router as importacion_router
from app.api.imagenes import router as imagenes_router
from app.api.visual import router as visual_router, admin_router as visual_admin_router
from app.api.alertas import router as alertas_router
from app.api.directorio import router as directorio_router
from app.api.iot import router as iot_router
from app.api.terminos import router as terminos_router
from app.api.sso_microsoft import router as sso_router, admin_router as sso_admin_router
from app.api.gastos import router as gastos_router

api_router = APIRouter(prefix="/api")
api_router.include_router(auth_router)
api_router.include_router(tickets_router)
api_router.include_router(equipos_router)
api_router.include_router(checklists_router)
api_router.include_router(reglas_router)
api_router.include_router(sitios_router)
api_router.include_router(kb_router)
api_router.include_router(chat_router)
api_router.include_router(metricas_router)
api_router.include_router(eventos_router)
api_router.include_router(conciencia_router)
api_router.include_router(conciencia_admin_router)
api_router.include_router(temas_router)
api_router.include_router(adjuntos_router)
api_router.include_router(estado_router)
api_router.include_router(estado_admin_router)
api_router.include_router(auditoria_router)
api_router.include_router(asistente_router)
api_router.include_router(soluciones_router)
api_router.include_router(resguardos_router)
api_router.include_router(expediente_router)
api_router.include_router(documentos_router)
api_router.include_router(cuentas_publico_router)
api_router.include_router(cuentas_admin_router)
api_router.include_router(documentacion_router)
api_router.include_router(importacion_router)
api_router.include_router(imagenes_router)
api_router.include_router(visual_router)
api_router.include_router(visual_admin_router)
api_router.include_router(alertas_router)
api_router.include_router(directorio_router)
api_router.include_router(iot_router)
api_router.include_router(terminos_router)
api_router.include_router(sso_router)
api_router.include_router(sso_admin_router)
api_router.include_router(gastos_router)
