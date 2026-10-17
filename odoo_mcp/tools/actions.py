from odoo_mcp import audit, guardrails, skills
from odoo_mcp.runtime import get_deps
from odoo_mcp.tools import mcp_tool


@mcp_tool
def run_action(model: str, ids: list, action: str,
               confirmation_token: str = None) -> dict:
    """Exécute une action de workflow Odoo (ex. action_confirm sur un devis).
    Seules les actions inscrites en liste blanche sont autorisées."""
    deps = get_deps()
    allowed = deps.config.allowed_actions.get(model, [])
    if action not in allowed:
        return {"status": "refuse",
                "message": f"Action '{action}' non autorisée sur {model}. "
                           f"Actions autorisées : {', '.join(allowed) or 'aucune'}."}
    deps.odoo.call_action(model, ids, action)
    audit.record(deps.config.audit_log_path, f"action:{action}", model, list(ids),
                 f"action {action} exécutée", "success")
    return {"status": "executed", "ids": list(ids), "action": action}


@mcp_tool
def post_message(model: str, record_id: int, body: str) -> dict:
    """Ajoute une note interne dans le fil de discussion (chatter) d'un record.
    N'envoie aucun email."""
    deps = get_deps()
    deps.odoo.post_message(model, record_id, body)
    audit.record(deps.config.audit_log_path, "post_message", model, [record_id],
                 "note interne ajoutée", "success")
    return {"status": "posted", "record_id": record_id}


@mcp_tool
def send_email(model: str, record_id: int, partner_ids: list, subject: str,
               body: str, confirmation_token: str = None) -> dict:
    """Envoie un véritable email aux contacts donnés depuis Odoo, tracé dans le
    chatter du record. Demande une confirmation explicite (email difficile à
    rétracter)."""
    deps = get_deps()
    descriptor = f"send_email:{model}:{record_id}:{sorted(partner_ids)}:{subject}"
    token = guardrails.needs_confirmation(descriptor, confirmation_token)
    if token is not None:
        return {"status": "confirmation_requise", "confirmation_token": token,
                "message": f"Email '{subject}' vers {len(partner_ids)} destinataire(s). "
                           f"Rappelez send_email avec confirmation_token pour envoyer."}
    deps.odoo.send_email(model, record_id, partner_ids, subject, body)
    audit.record(deps.config.audit_log_path, "send_email", model, [record_id],
                 f"email '{subject}' envoyé à {len(partner_ids)} destinataire(s)",
                 "success")
    return {"status": "sent", "record_id": record_id}


@mcp_tool
def attach_file(model: str, record_id: int, filename: str,
                content_base64: str) -> dict:
    """Joint un fichier (encodé en base64) à un record."""
    deps = get_deps()
    attachment_id = deps.odoo.create("ir.attachment", {
        "name": filename,
        "datas": content_base64,
        "res_model": model,
        "res_id": record_id,
    })
    audit.record(deps.config.audit_log_path, "attach_file", model, [record_id],
                 f"fichier '{filename}' joint", "success")
    return {"status": "attached", "attachment_id": attachment_id}


@mcp_tool
def get_attachments(model: str, record_id: int) -> list:
    """Liste les pièces jointes d'un record et renvoie leur contenu (base64).
    Permet de récupérer les PDF générés par Odoo (factures, etc.)."""
    deps = get_deps()
    # Odoo masque par défaut les pièces jointes rattachées à un champ binaire
    # (res_field renseigné), dont le PDF officiel d'une facture
    # (invoice_pdf_report_id). Le OR explicite sur res_field les inclut.
    return deps.odoo.search("ir.attachment",
                            domain=[["res_model", "=", model],
                                    ["res_id", "=", record_id],
                                    "|", ["res_field", "=", False],
                                    ["res_field", "!=", False]],
                            fields=["name", "mimetype", "datas"])


@mcp_tool
def audit_log(limit: int = 50) -> list:
    """Renvoie les dernières entrées du journal d'audit (quoi et quand)."""
    deps = get_deps()
    return audit.read_recent(deps.config.audit_log_path, limit=limit)


@mcp_tool
def list_skills_tool() -> list:
    """Liste les savoir-faire métier disponibles (nom + description)."""
    return skills.list_skills(get_deps().config.skills_dir)


@mcp_tool
def get_skill_tool(name: str) -> str:
    """Renvoie le contenu complet d'un savoir-faire métier par son nom."""
    return skills.get_skill(get_deps().config.skills_dir, name)
