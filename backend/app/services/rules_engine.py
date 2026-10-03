from sqlalchemy.orm import Session
from app.models import ReglaNegocio
from app.core.logging import logger
from app.services.ollama_client import normalizar_categoria

class RulesEngine:
    @staticmethod
    def evaluate_and_apply_rules(db: Session, sitio_id: int, categoria: str, descripcion: str) -> dict:
        """
        Evaluates active business rules for a given site and category.
        Returns evaluation dict with overriding attributes if a rule matches.
        """
        # Fetch active rules for site and category
        rules = db.query(ReglaNegocio).filter(
            ReglaNegocio.sitio_id == sitio_id,
            # **Exacta, y aquí importa más que en ningún otro sitio.** Con
            # `ILIKE`, una categoría con `%` habría hecho coincidir reglas de
            # *todas* las categorías: la regla de impresoras aplicándose a un
            # ticket de red cambia su SLA y a quién se escala. Lo que no es una
            # categoría no casa con ninguna regla, y el ticket se queda con su
            # trato por defecto.
            ReglaNegocio.categoria == (normalizar_categoria(categoria) or ""),
            ReglaNegocio.activa == True
        ).all()

        result = {
            "matched": False,
            "rule_id": None,
            "accion": None,
            "estado": None,
            "canal_resolucion": None,
            "destinatario": None,
            "nota": None,
            # Prioridad que impone la regla, si impone alguna. None = se
            # respeta la que eligio quien reporto.
            "prioridad": None,
            # Solucion con la que queda un ticket auto-resuelto por regla. Sin
            # esto el ticket quedaba "resuelto" sin explicacion, que es
            # justamente lo que el cierre manual tiene prohibido.
            "solucion": None,
        }

        for rule in rules:
            # Check condition (broad match or hardware check)
            cond = (rule.condicion or "").strip().lower()
            desc = descripcion.lower()
            # Una condición en blanco está contenida en cualquier descripción:
            # casaría con todo. El alta ya la rechaza; esto cubre las que se
            # guardaron antes. Para abarcar todo a propósito está «*».
            if not cond:
                continue

            # Rule match check
            if cond in desc or cond == "*" or cond == rule.categoria.lower():
                result["matched"] = True
                result["rule_id"] = rule.id
                result["accion"] = rule.accion
                result["destinatario"] = rule.destinatario

                if rule.accion == "proveedor":
                    result["estado"] = "espera_proveedor"
                    result["canal_resolucion"] = "proveedor"
                    result["nota"] = f"Regla de negocio #{rule.id} aplicada: Redirigido a proveedor externo ({rule.destinatario})."
                elif rule.accion == "escalar":
                    result["estado"] = "abierto"
                    result["canal_resolucion"] = "tecnico"
                    # "Escalar con maxima prioridad" tiene que subir la
                    # prioridad de verdad: antes solo escribia una nota
                    # diciendo que lo habia escalado, y el SLA seguia siendo
                    # el que eligio quien reporto.
                    result["prioridad"] = "critica"
                    result["nota"] = (
                        f"Regla de negocio #{rule.id} aplicada: escalado con prioridad crítica."
                    )
                elif rule.accion == "auto":
                    result["estado"] = "resuelto"
                    result["canal_resolucion"] = "checklist"
                    result["solucion"] = (
                        f"Resuelto automáticamente por la regla de negocio #{rule.id} "
                        f"({rule.categoria} / «{rule.condicion}»). "
                        "Revise la regla si el cierre no corresponde."
                    )
                    result["nota"] = f"Regla de negocio #{rule.id} aplicada: Auto-resuelto por sistema."
                
                logger.info("Business rule matched", extra={"rule_id": rule.id, "accion": rule.accion, "sitio_id": sitio_id})
                break

        return result
