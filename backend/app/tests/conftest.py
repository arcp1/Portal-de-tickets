import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.db import Base, get_db
from app.main import app
from app.core.security import get_password_hash
from app.models import Sitio, Usuario

SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture(autouse=True)
def ia_desactivada_por_defecto(monkeypatch):
    """La suite no toca la red.

    Las pruebas que necesitan ejercitar la degradación de Ollama la vuelven a
    activar apuntando a un host muerto (ver test_ia_nunca_bloquea.py).
    """
    monkeypatch.setattr(settings, "IA_HABILITADA", False)

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@pytest.fixture(scope="function")
def db_session():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    
    # Create seed site
    site = Sitio(clave="QRO", nombre="Planta Querétaro", pais="México", activo=True)
    db.add(site)
    db.commit()
    db.refresh(site)

    # Create admin
    admin = Usuario(
        sitio_id=site.id,
        nombre="Admin Test",
        email="admin@test.com",
        password_hash=get_password_hash("Secret123!"),
        rol="admin",
        activo=True
    )
    # Create user
    user = Usuario(
        sitio_id=site.id,
        nombre="User Test",
        email="user@test.com",
        password_hash=get_password_hash("Secret123!"),
        rol="usuario",
        activo=True
    )
    db.add_all([admin, user])
    db.commit()

    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)

@pytest.fixture(scope="function")
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()
