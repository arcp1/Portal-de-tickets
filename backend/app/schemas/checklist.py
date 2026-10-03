from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.networks import validate_email
from pydantic_core import PydanticCustomError
from typing import List, Literal, Optional

from app.schemas.imagenes import ImagenBreve

class ChecklistCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    categoria: str = Field(max_length=50)
    orden: int = Field(default=1, ge=1, le=1000)
    pregunta_key: str = Field(min_length=1, max_length=100)
    accion_si_no: Optional[str] = Field(default=None, max_length=5000)
    resuelve: bool = False

class ChecklistResponse(BaseModel):
    id: int
    categoria: str
    orden: int
    pregunta_key: str
    # Los pasos sembrados traen llave de traduccion; los que crea el admin
    # desde el portal traen el texto directo aqui.
    pregunta_texto: Optional[str] = None
    accion_si_no: Optional[str] = None
    resuelve: bool
    # Dónde está el botón, qué luz tiene que estar encendida: el paso que se
    # sigue mirando en vez de leyendo.
    imagenes: List[ImagenBreve] = []

    model_config = ConfigDict(from_attributes=True)

class ReglaCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    # Sin ella se usa la única planta que haya; con varias, se pide.
    sitio_id: Optional[int] = None
    categoria: str
    # **Una condición vacía casaba con todo.** El motor pregunta si la condición
    # está contenida en la descripción, y la cadena vacía está contenida en
    # cualquier texto: una regla guardada con espacios —el formulario los
    # recorta a nada— se aplicaba a cada ticket de su categoría, y con la
    # acción «auto» los daba por resueltos sin que nadie los viera. Para
    # abarcarlos todos a propósito está el comodín «*».
    condicion: str = Field(min_length=1, max_length=100)
    # Una acción inventada se guardaba y la regla casaba sin hacer nada.
    accion: Literal["proveedor", "escalar", "auto"]
    destinatario: Optional[str] = Field(default=None, max_length=100)
    activa: bool = True

    @model_validator(mode="after")
    def _proveedor_con_destino(self):
        # «Enrutar a proveedor» sin correo no avisa a nadie. El formulario ya
        # lo pedía; el API lo dejaba pasar.
        if self.accion == "proveedor" and not self.destinatario:
            raise ValueError("enrutar a proveedor necesita un destinatario")
        # Y tiene que ser un correo: el aviso al proveedor sale por correo a
        # esta dirección. "esto no es un correo" se guardaba, el ticket pasaba
        # a "en proveedor" y el envío fallaba sin que nadie se enterara. Se
        # guarda la dirección sola, aunque se escriba "Soporte <s@zebra.com>".
        if self.accion == "proveedor":
            try:
                _, self.destinatario = validate_email(self.destinatario)
            except (PydanticCustomError, ValueError):
                raise ValueError("el destinatario de un proveedor debe ser un correo válido")
        return self

class ReglaResponse(BaseModel):
    id: int
    sitio_id: int
    categoria: str
    condicion: str
    accion: str
    destinatario: Optional[str] = None
    activa: bool

    model_config = ConfigDict(from_attributes=True)
