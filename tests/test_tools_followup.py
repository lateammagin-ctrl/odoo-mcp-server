import base64

import odoo_mcp.runtime as runtime
from odoo_mcp.config import Config
from odoo_mcp.odoo_client import OdooClient, OdooError
from odoo_mcp.runtime import Deps
from odoo_mcp.tools.actions import get_attachments
from odoo_mcp.tools.followup import send_payment_reminder


def _config(tmp_path):
    return Config(
        odoo_url="https://x", odoo_db="db", odoo_username="u", odoo_api_key="k",
        access_secret="s", allowed_models=["res.partner", "account.move"],
        allowed_actions={}, mass_op_cap=50,
        audit_log_path=str(tmp_path / "audit.log"), skills_dir=str(tmp_path),
    )


def _move(mid, name, residual, pdf=None, partner=10, state="posted",
          payment_state="not_paid", move_type="out_invoice"):
    return {"id": mid, "name": name, "move_type": move_type, "state": state,
            "payment_state": payment_state, "commercial_partner_id": [partner, "X"],
            "invoice_date": "2026-06-01", "invoice_date_due": "2026-06-15",
            "amount_residual": residual, "currency_id": [1, "EUR"],
            "invoice_pdf_report_id": [pdf, f"{name}.pdf"] if pdf else False}


class FakeOdoo:
    def __init__(self, moves, template_model="res.partner", emails=None):
        self.moves = {m["id"]: m for m in moves}
        self.template_model = template_model
        self.emails = emails or {10: "client@ex.be", 11: "compta@ex.be"}
        self.sent, self.notes, self.created, self.fetched = [], [], [], []

    def read(self, model, ids, fields=None):
        if model == "mail.template":
            return [{"id": i, "name": "Payment Reminder", "model": self.template_model}
                    for i in ids]
        if model == "res.partner":
            return [{"id": i, "name": f"P{i}", "commercial_partner_id": [10, "X"],
                     "email": self.emails.get(i, False)} for i in ids if i in self.emails]
        if model == "account.move":
            return [self.moves[i] for i in ids if i in self.moves]
        raise AssertionError(model)

    def search(self, model, domain=None, fields=None, limit=None, offset=0, order=None):
        assert model == "account.move"
        return list(self.moves.values())

    def fetch_invoice_pdf(self, move_id):
        self.fetched.append(move_id)
        return b"%PDF-1.7 fake"

    def create(self, model, values):
        self.created.append((model, values))
        return 900 + len(self.created)

    def send_mail_template(self, template_id, res_id, email_values=None):
        self.sent.append((template_id, res_id, email_values))
        return 555

    def post_message(self, model, record_id, body):
        self.notes.append((model, record_id, body))


def _run(tmp_path, odoo, **kwargs):
    runtime.deps = Deps(config=_config(tmp_path), odoo=odoo)
    first = send_payment_reminder(**kwargs)
    if first["status"] != "confirmation_requise":
        return first, None
    second = send_payment_reminder(confirmation_token=first["confirmation_token"], **kwargs)
    return first, second


def test_preview_then_send_with_existing_pdfs(tmp_path):
    odoo = FakeOdoo([_move(1, "INV/2026/00109", 203.28, pdf=11003),
                     _move(2, "INV/2026/00168", 203.28, pdf=12525)])
    first, second = _run(tmp_path, odoo, partner_id=10, template_id=44)

    assert first["status"] == "confirmation_requise"
    assert first["total_factures"] == "406,56 €"
    assert len(first["factures"]) == 2

    assert second["status"] == "sent"
    assert odoo.sent == [(44, 10, {"attachment_ids": [11003, 12525],
                                   "recipient_ids": [[6, 0, [10]]]})]
    assert odoo.fetched == [] and odoo.created == []
    noted = {(m, r) for m, r, _ in odoo.notes}
    assert noted == {("res.partner", 10), ("account.move", 1), ("account.move", 2)}


def test_nothing_sent_without_token(tmp_path):
    odoo = FakeOdoo([_move(1, "INV/1", 10.0, pdf=5)])
    runtime.deps = Deps(config=_config(tmp_path), odoo=odoo)
    result = send_payment_reminder(partner_id=10, template_id=44)
    assert result["status"] == "confirmation_requise"
    assert odoo.sent == [] and odoo.notes == []


def test_missing_pdf_is_generated_and_attached_to_invoice(tmp_path):
    odoo = FakeOdoo([_move(3, "INV/2026/00095", 38.72)])
    _, second = _run(tmp_path, odoo, partner_id=10, template_id=51)
    assert second["status"] == "sent"
    assert odoo.fetched == [3]
    model, values = odoo.created[0]
    assert model == "ir.attachment"
    assert values["name"] == "INV_2026_00095.pdf"
    assert values["res_model"] == "account.move" and values["res_id"] == 3
    assert base64.b64decode(values["datas"]).startswith(b"%PDF")
    assert odoo.sent[0][2]["attachment_ids"] == [901]


def test_custom_recipients(tmp_path):
    odoo = FakeOdoo([_move(1, "INV/1", 10.0, pdf=5)])
    _, second = _run(tmp_path, odoo, partner_id=10, template_id=44,
                     recipient_partner_ids=[11, 10])
    assert second["destinataires"] == ["compta@ex.be", "client@ex.be"]
    assert odoo.sent[0][2]["recipient_ids"] == [[6, 0, [11, 10]]]


def test_refuses_paid_or_foreign_invoice(tmp_path):
    odoo = FakeOdoo([_move(1, "INV/1", 0.0, pdf=5, payment_state="paid"),
                     _move(2, "INV/2", 10.0, pdf=6, partner=99)])
    runtime.deps = Deps(config=_config(tmp_path), odoo=odoo)
    result = send_payment_reminder(partner_id=10, template_id=44, invoice_ids=[1, 2])
    assert result["status"] == "refuse"
    assert "déjà payée" in result["message"]
    assert "autre client" in result["message"]
    assert odoo.sent == []


def test_refuses_template_on_wrong_model(tmp_path):
    odoo = FakeOdoo([_move(1, "INV/1", 10.0, pdf=5)], template_model="account.move")
    runtime.deps = Deps(config=_config(tmp_path), odoo=odoo)
    result = send_payment_reminder(partner_id=10, template_id=7)
    assert result["status"] == "refuse"


def test_refuses_recipient_without_email(tmp_path):
    odoo = FakeOdoo([_move(1, "INV/1", 10.0, pdf=5)], emails={10: False})
    runtime.deps = Deps(config=_config(tmp_path), odoo=odoo)
    result = send_payment_reminder(partner_id=10, template_id=44)
    assert result["status"] == "refuse"


def test_send_failure_is_reported_and_no_note(tmp_path):
    odoo = FakeOdoo([_move(1, "INV/1", 10.0, pdf=5)])

    def boom(*a, **k):
        raise OdooError("serveur mail indisponible")
    odoo.send_mail_template = boom
    _, second = _run(tmp_path, odoo, partner_id=10, template_id=44)
    assert second["status"] == "erreur"
    assert odoo.notes == []


def test_client_send_mail_template_call(fake_odoo):
    client = OdooClient("https://x", "db", "u", "k", ["mail.template"])
    client.execute_kw = fake_odoo
    client.send_mail_template(44, 10, {"attachment_ids": [1]})
    model, method, args, kwargs = fake_odoo.calls[0]
    assert (model, method, args) == ("mail.template", "send_mail", [[44]])
    assert kwargs == {"res_id": 10, "force_send": True,
                      "email_values": {"attachment_ids": [1]}}


def test_get_attachments_includes_field_attachments(tmp_path):
    seen = {}

    class Odoo:
        def search(self, model, domain=None, fields=None, **kw):
            seen["domain"] = domain
            return []
    runtime.deps = Deps(config=_config(tmp_path), odoo=Odoo())
    get_attachments("account.move", 3)
    assert ["res_field", "!=", False] in seen["domain"]
