from fastapi import APIRouter
from app.api.auth import router as auth_router
from app.api.tickets import router as tickets_router
from app.api.equipos import router as equipos_router
from app.api.checklists import router as checklists_router
from app.api.reglas import router as reglas_router
from app.api.sitios import router as sitios_router
from app.api.kb import router as kb_router
from app.api.chat import router as chat_router

api_router = APIRouter(prefix="/api")
api_router.include_router(auth_router)
api_router.include_router(tickets_router)
api_router.include_router(equipos_router)
api_router.include_router(checklists_router)
api_router.include_router(reglas_router)
api_router.include_router(sitios_router)
api_router.include_router(kb_router)
api_router.include_router(chat_router)
