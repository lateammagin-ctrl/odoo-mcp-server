import pytest
from odoo_mcp.odoo_client import OdooClient, OdooError


def make_client():
    return OdooClient("https://x.odoo.com/", "db", "user", "key",
                      allowed_models=["crm.lead", "res.partner"])


def make_marketing_client():
    """Client configuré comme en production pour le pack marketing :
    marketing.campaign modifiable mais `state` gelé, ir.actions.server
    consultable seulement."""
    return OdooClient(
        "https://x.odoo.com/", "db", "user", "key",
        allowed_models=["marketing.campaign", "marketing.activity"],
        readonly_models=["ir.actions.server", "ir.model"],
        frozen_fields={"marketing.campaign": ["state"]},
    )


def test_check_model_rejects_unlisted():
    client = make_client()
    with pytest.raises(OdooError) as exc:
        client.execute_kw("res.users", "search", [[]])
    assert "non autorisé" in str(exc.value)


def test_execute_kw_uses_uid_and_returns_result(monkeypatch):
    client = make_client()
    monkeypatch.setattr(client, "_ensure_uid", lambda: 2)

    captured = {}

    class FakeModels:
        def execute_kw(self, db, uid, key, model, method, args, kwargs):
            captured.update(db=db, uid=uid, model=model, method=method)
            return [42]

    client._models = FakeModels()
    result = client.execute_kw("crm.lead", "search", [[]])
    assert result == [42]
    assert captured == {"db": "db", "uid": 2, "model": "crm.lead", "method": "search"}


def test_read_methods_delegate_to_execute_kw(monkeypatch):
    client = make_client()
    seen = []
    monkeypatch.setattr(client, "execute_kw",
                        lambda m, meth, a, k=None: seen.append((m, meth, a, k)) or "OK")

    client.search("crm.lead", domain=[["name", "=", "x"]], fields=["name"],
                  limit=5, offset=2, order="id desc")
    client.read("crm.lead", [1, 2], fields=["name"])
    client.fields("crm.lead")
    client.count("crm.lead", domain=[])
    client.read_group("crm.lead", domain=[], fields=["expected_revenue:sum"],
                      groupby=["stage_id"])

    assert seen[0] == ("crm.lead", "search_read",
                       [[["name", "=", "x"]]],
                       {"fields": ["name"], "limit": 5, "offset": 2, "order": "id desc"})
    assert seen[1] == ("crm.lead", "read", [[1, 2]], {"fields": ["name"]})
    assert seen[2] == ("crm.lead", "fields_get", [], {"attributes": ["string", "type", "required", "selection", "relation"]})
    assert seen[3] == ("crm.lead", "search_count", [[]], None)
    assert seen[4] == ("crm.lead", "read_group", [[], ["expected_revenue:sum"], ["stage_id"]], None)


def test_write_methods_delegate(monkeypatch):
    client = make_client()
    seen = []
    monkeypatch.setattr(client, "execute_kw",
                        lambda m, meth, a, k=None: seen.append((m, meth, a)) or 99)

    client.create("crm.lead", {"name": "ACME"})
    client.write("crm.lead", [5], {"name": "ACME2"})
    client.unlink("crm.lead", [5])

    assert seen[0] == ("crm.lead", "create", [{"name": "ACME"}])
    assert seen[1] == ("crm.lead", "write", [[5], {"name": "ACME2"}])
    assert seen[2] == ("crm.lead", "unlink", [[5]])


def test_readonly_model_allows_reading(monkeypatch):
    client = make_marketing_client()
    monkeypatch.setattr(client, "_ensure_uid", lambda: 2)

    class FakeModels:
        def execute_kw(self, db, uid, key, model, method, args, kwargs):
            return [{"id": 3, "name": "Créer une tâche"}]

    client._models = FakeModels()
    assert client.search("ir.actions.server", fields=["name"]) == [
        {"id": 3, "name": "Créer une tâche"}]
    assert client.fields("ir.model")  # fields_get compte comme une lecture


def test_readonly_model_refuses_every_write():
    client = make_marketing_client()
    for call in (
        lambda: client.create("ir.actions.server", {"name": "x"}),
        lambda: client.write("ir.actions.server", [1], {"name": "x"}),
        lambda: client.unlink("ir.actions.server", [1]),
        # Une action de workflow est elle aussi une écriture : le refus par
        # défaut sur les méthodes inconnues doit l'attraper.
        lambda: client.call_action("ir.actions.server", [1], "run"),
    ):
        with pytest.raises(OdooError) as exc:
            call()
        assert "lecture seule" in str(exc.value)


def test_unlisted_model_still_refused_and_lists_both_sets():
    client = make_marketing_client()
    with pytest.raises(OdooError) as exc:
        client.search("res.users")
    message = str(exc.value)
    assert "non autorisé" in message
    # Le message d'aide énumère les modèles des deux listes.
    assert "marketing.campaign" in message and "ir.model" in message


def test_frozen_field_refused_on_write_and_create():
    client = make_marketing_client()
    with pytest.raises(OdooError) as exc:
        client.write("marketing.campaign", [1], {"state": "running"})
    assert "state" in str(exc.value)
    # Interdit aussi de naître directement en « running ».
    with pytest.raises(OdooError):
        client.create("marketing.campaign", {"name": "X", "state": "running"})


def test_frozen_field_lets_other_fields_through(monkeypatch):
    client = make_marketing_client()
    seen = []
    monkeypatch.setattr(client, "execute_kw",
                        lambda m, meth, a, k=None: seen.append((m, meth, a)) or 12)

    client.write("marketing.campaign", [1], {"enroll_domain": "[]"})
    client.create("marketing.activity", {"name": "Relance",
                                         "trigger_type": "mail_not_open"})

    assert seen[0] == ("marketing.campaign", "write", [[1], {"enroll_domain": "[]"}])
    assert seen[1][1] == "create"


def test_action_message_email_delegate(monkeypatch):
    client = make_client()
    seen = []
    monkeypatch.setattr(client, "execute_kw",
                        lambda m, meth, a, k=None: seen.append((m, meth, a, k)) or True)

    client.call_action("sale.order", [3], "action_confirm")
    client.post_message("crm.lead", 8, "Note interne")
    client.send_email("crm.lead", 8, [12], "Bonjour", "<p>Corps</p>")

    assert seen[0] == ("sale.order", "action_confirm", [[3]], None)
    assert seen[1][:3] == ("crm.lead", "message_post", [[8]])
    assert seen[1][3]["body"] == "Note interne"
    assert seen[2][1] == "message_post"
    assert seen[2][3]["partner_ids"] == [12]
    assert seen[2][3]["subject"] == "Bonjour"
