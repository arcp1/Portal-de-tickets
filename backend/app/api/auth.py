from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from app.core.db import get_db
from app.core.security import verify_password, get_password_hash, create_access_token
from app.models import Usuario
from app.schemas.auth import LoginRequest, TokenResponse, UserResponse, UserCreate
from app.api.deps import get_current_user, get_current_admin

router = APIRouter(prefix="/auth", tags=["Auth"])

@router.post("/login", response_model=TokenResponse)
def login(request: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(Usuario).filter(Usuario.email == request.email).first()
    if not user or not verify_password(request.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password"
        )
    if not user.activo:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User account is deactivated"
        )
    
    access_token = create_access_token(subject=user.id)
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user=user
    )

@router.post("/login/form", response_model=TokenResponse)
def login_form(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(Usuario).filter(Usuario.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password"
        )
    
    access_token = create_access_token(subject=user.id)
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user=user
    )

@router.get("/me", response_model=UserResponse)
def read_current_user(current_user: Usuario = Depends(get_current_user)):
    return current_user

@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register_user(
    user_in: UserCreate, 
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin)
):
    existing = db.query(Usuario).filter(Usuario.email == user_in.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    user = Usuario(
        sitio_id=user_in.sitio_id,
        nombre=user_in.nombre,
        email=user_in.email,
        password_hash=get_password_hash(user_in.password),
        rol=user_in.rol,
        area=user_in.area,
        idioma_preferido=user_in.idioma_preferido,
        activo=True
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
