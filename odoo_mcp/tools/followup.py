"""Relances de paiement envoyées entièrement depuis Odoo.

Un seul appel par client : Odoo rend le modèle d'email choisi, y joint le PDF
officiel de chaque facture concernée, envoie le mail depuis son propre serveur
et la relance est tracée par une note dans l'historique du client et de chaque
facture. Aucun PDF ne transite par le connecteur.
"""
import base64
from datetime import date

from odoo_mcp import audit, guardrails
from odoo_mcp.odoo_client import OdooError
from odoo_mcp.runtime import get_deps
from odoo_mcp.tools import mcp_tool

_UNPAID = ("not_paid", "partial")
_MOVE_FIELDS = ["name", "move_type", "state", "payment_state",
                "commercial_partner_id", "invoice_date", "invoice_date_due",
                "amount_residual", "currency_id", "invoice_pdf_report_id"]


def _m2o_id(value):
    return value[0] if isinstance(value, (list, tuple)) and value else value


def _fmt_amount(value):
    return f"{value:,.2f} €".replace(",", " ").replace(".", ",")


def _fmt_date(value):
    if not value:
        return "?"
    y, m, d = str(value)[:10].split("-")
    return f"{d}/{m}/{y}"


def _overdue_invoices(odoo, commercial_id):
    return odoo.search("account.move", domain=[
        ["move_type", "=", "out_invoice"],
        ["state", "=", "posted"],
        ["payment_state", "in", list(_UNPAID)],
        ["commercial_partner_id", "=", commercial_id],
        ["invoice_date_due", "<", date.today().isoformat()],
    ], fields=_MOVE_FIELDS, order="invoice_date_due asc")


def _invoice_problems(moves, requested_ids, commercial_id):
    found = {m["id"] for m in moves}
    problems = [f"facture {i} introuvable" for i in requested_ids if i not in found]
    for m in moves:
        if m["move_type"] != "out_invoice":
            problems.append(f"{m['name']} n'est pas une facture client")
        elif m["state"] != "posted":
            problems.append(f"{m['name']} n'est pas validée")
        elif m["payment_state"] not in _UNPAID:
            problems.append(f"{m['name']} est déjà payée ({m['payment_state']})")
        if _m2o_id(m["commercial_partner_id"]) != commercial_id:
            problems.append(f"{m['name']} appartient à un autre client")
    return problems


def _pdf_attachment_id(odoo, move):
    """Id de la pièce jointe PDF officielle de la facture. Si Odoo ne l'a
    jamais générée, on la fait générer et on la range sur la facture."""
    existing = _m2o_id(move.get("invoice_pdf_report_id"))
    if existing:
        return existing
    content = odoo.fetch_invoice_pdf(move["id"])
    return odoo.create("ir.attachment", {
        "name": move["name"].replace("/", "_") + ".pdf",
        "datas": base64.b64encode(content).decode("ascii"),
        "mimetype": "application/pdf",
        "res_model": "account.move",
        "res_id": move["id"],
    })


@mcp_tool
def send_payment_reminder(partner_id: int, template_id: int,
                          invoice_ids: list = None,
                          recipient_partner_ids: list = None,
                          confirmation_token: str = None) -> dict:
    """Envoie une relance de paiement à un client, depuis Odoo, avec le PDF de
    chaque facture concernée en pièce jointe.

    - partner_id : le client (res.partner).
    - template_id : modèle d'email de relance (mail.template sur res.partner,
      ex. « Payment Reminder », « Rappel de paiement (2) »…).
    - invoice_ids : factures à joindre. Par défaut, toutes les factures
      client validées, impayées et échues de ce client.
    - recipient_partner_ids : destinataires (contacts res.partner). Par
      défaut, le client lui-même. Utile pour viser le contact comptabilité.

    Le montant affiché dans le mail est celui calculé par le modèle (en
    général le total échu du client). Premier appel : renvoie un aperçu et un
    jeton, sans rien envoyer. Second appel avec le jeton : envoie réellement,
    puis trace la relance par une note sur le client et sur chaque facture."""
    deps = get_deps()
    odoo = deps.odoo
    try:
        templates = odoo.read("mail.template", [template_id], ["name", "model"])
        if not templates:
            return {"status": "refuse", "message": f"Modèle {template_id} introuvable."}
        template = templates[0]
        if template.get("model") != "res.partner":
            return {"status": "refuse",
                    "message": f"Le modèle « {template['name']} » porte sur "
                               f"{template.get('model')} : une relance attend un "
                               f"modèle sur res.partner."}

        partners = odoo.read("res.partner", [partner_id],
                             ["name", "commercial_partner_id"])
        if not partners:
            return {"status": "refuse", "message": f"Client {partner_id} introuvable."}
        partner = partners[0]
        commercial_id = _m2o_id(partner["commercial_partner_id"]) or partner_id

        if invoice_ids:
            moves = odoo.read("account.move", list(invoice_ids), _MOVE_FIELDS)
            problems = _invoice_problems(moves, list(invoice_ids), commercial_id)
            if problems:
                return {"status": "refuse",
                        "message": "Relance refusée : " + " ; ".join(problems) + "."}
        else:
            moves = _overdue_invoices(odoo, commercial_id)
        if not moves:
            return {"status": "refuse",
                    "message": f"Aucune facture échue et impayée pour {partner['name']}."}

        recipient_ids = list(recipient_partner_ids or [partner_id])
        recipients = odoo.read("res.partner", recipient_ids, ["name", "email"])
        missing = [r["name"] for r in recipients if not r.get("email")]
        if missing or len(recipients) != len(recipient_ids):
            return {"status": "refuse",
                    "message": "Destinataire(s) sans adresse email ou introuvable(s) : "
                               + (", ".join(missing) or "ids inconnus") + "."}
    except OdooError as exc:
        return {"status": "erreur", "message": str(exc)}

    move_ids = sorted(m["id"] for m in moves)
    total = sum(m["amount_residual"] for m in moves)
    lines = [f"{m['name']} échue le {_fmt_date(m['invoice_date_due'])} : "
             f"{_fmt_amount(m['amount_residual'])}" for m in moves]
    emails = [r["email"] for r in recipients]

    descriptor = (f"payment_reminder:{partner_id}:{template_id}:"
                  f"{move_ids}:{sorted(recipient_ids)}")
    token = guardrails.needs_confirmation(descriptor, confirmation_token)
    if token is not None:
        return {"status": "confirmation_requise", "confirmation_token": token,
                "client": partner["name"], "modele": template["name"],
                "destinataires": emails, "factures": lines,
                "total_factures": _fmt_amount(total),
                "message": f"Relance « {template['name']} » à {partner['name']} "
                           f"({', '.join(emails)}) avec {len(moves)} facture(s) "
                           f"en annexe. Rappelez send_payment_reminder avec "
                           f"confirmation_token pour envoyer."}

    try:
        attachment_ids = [_pdf_attachment_id(odoo, m) for m in moves]
        mail_id = odoo.send_mail_template(template_id, partner_id, {
            "attachment_ids": attachment_ids,
            "recipient_ids": [[6, 0, recipient_ids]],
        })
    except OdooError as exc:
        audit.record(deps.config.audit_log_path, "send_payment_reminder",
                     "res.partner", [partner_id], f"échec : {exc}", "error")
        return {"status": "erreur", "message": str(exc)}

    # Traçabilité : un mail envoyé par modèle n'apparaît pas toujours dans le
    # chatter, d'où une note interne (aucun email) sur le client et les factures.
    note = (f"Relance de paiement « {template['name']} » envoyée le "
            f"{_fmt_date(date.today().isoformat())} à {', '.join(emails)}. "
            f"Factures jointes : {' ; '.join(lines)}.")
    for model, rid in [("res.partner", partner_id)] + [("account.move", i) for i in move_ids]:
        try:
            odoo.post_message(model, rid, note)
        except OdooError:
            pass  # le mail est parti : une note manquante ne doit pas masquer l'envoi

    audit.record(deps.config.audit_log_path, "send_payment_reminder", "res.partner",
                 [partner_id],
                 f"relance « {template['name']} » envoyée à {', '.join(emails)} "
                 f"avec {len(moves)} facture(s) : {', '.join(m['name'] for m in moves)}",
                 "success")
    return {"status": "sent", "mail_id": mail_id, "client": partner["name"],
            "destinataires": emails, "factures": lines,
            "pieces_jointes": attachment_ids}
