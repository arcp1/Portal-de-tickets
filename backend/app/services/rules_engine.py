from sqlalchemy.orm import Session
from app.models import ReglaNegocio, Ticket
from app.core.logging import logger

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
            ReglaNegocio.categoria.ilike(categoria),
            ReglaNegocio.activa == True
        ).all()

        result = {
            "matched": False,
            "rule_id": None,
            "accion": None,
            "estado": None,
            "canal_resolucion": None,
            "destinatario": None,
            "nota": None
        }

        for rule in rules:
            # Check condition (broad match or hardware check)
            cond = rule.condicion.lower()
            desc = descripcion.lower()

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
                    result["nota"] = f"Regla de negocio #{rule.id} aplicada: Escalado prioritario."
                elif rule.accion == "auto":
                    result["estado"] = "resuelto"
                    result["canal_resolucion"] = "checklist"
                    result["nota"] = f"Regla de negocio #{rule.id} aplicada: Auto-resuelto por sistema."
                
                logger.info("Business rule matched", extra={"rule_id": rule.id, "accion": rule.accion, "sitio_id": sitio_id})
                break

        return result
