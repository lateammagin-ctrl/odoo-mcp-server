import pytest
from odoo_mcp.config import Config


def _write(tmp_path, toml_text):
    p = tmp_path / "config.toml"
    p.write_text(toml_text, encoding="utf-8")
    return str(p)


def test_load_reads_env_and_toml(tmp_path, monkeypatch):
    for k, v in {
        "ODOO_URL": "https://magin.odoo.com/",
        "ODOO_DB": "magin",
        "ODOO_USERNAME": "team@magin.com",
        "ODOO_API_KEY": "key123",
        "MCP_ACCESS_SECRET": "secret123",
    }.items():
        monkeypatch.setenv(k, v)
    toml = _write(tmp_path, """
[models]
allowed = ["crm.lead", "res.partner"]
[actions]
"sale.order" = ["action_confirm"]
[guardrails]
mass_op_cap = 25
""")
    cfg = Config.load(toml_path=toml, env_path=str(tmp_path / "nonexistent.env"))
    assert cfg.odoo_url == "https://magin.odoo.com"  # slash final retiré
    assert cfg.allowed_models == ["crm.lead", "res.partner"]
    assert cfg.allowed_actions == {"sale.order": ["action_confirm"]}
    assert cfg.mass_op_cap == 25


def test_load_fails_on_missing_secret(tmp_path, monkeypatch):
    for k in ("ODOO_URL", "ODOO_DB", "ODOO_USERNAME", "ODOO_API_KEY", "MCP_ACCESS_SECRET"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ODOO_URL", "https://x")
    with pytest.raises(RuntimeError) as exc:
        Config.load(toml_path=str(tmp_path / "none.toml"), env_path=str(tmp_path / "none.env"))
    assert "ODOO_DB" in str(exc.value)


def test_load_example_config_has_extended_whitelist(monkeypatch, tmp_path):
    """Vérifie que config.example.toml du repo contient bien la liste blanche
    étendue : un échantillon de modèles et d'actions de chaque module clé."""
    for k, v in {
        "ODOO_URL": "https://example.odoo.com",
        "ODOO_DB": "db",
        "ODOO_USERNAME": "u",
        "ODOO_API_KEY": "k",
        "MCP_ACCESS_SECRET": "s",
    }.items():
        monkeypatch.setenv(k, v)
    # Charge le vrai config.example.toml du repo, env_path inexistant.
    cfg = Config.load(
        toml_path="config.example.toml",
        env_path=str(tmp_path / "missing.env"),
    )
    # Échantillon couvrant chaque module ajouté
    expected_models = {
        "project.task",          # project
        "social.post",           # social marketing
        "whatsapp.message",      # whatsapp
        "hr.expense",            # note de frais
        "pos.order",             # point de vente
        "crm.tag",               # crm étendu
        "website.page",          # site web
        "appointment.type",      # rendez-vous
        "stock.move",            # inventaire étendu
        "calendar.event",        # calendrier
        "planning.slot",         # planning
        "mailing.contact",       # email marketing étendu
        "purchase.requisition",  # achats étendu
        "documents.document",    # documents
        "spreadsheet.dashboard", # dashboards
        "mail.activity",         # transverse
        "uom.uom",               # transverse
    }
    assert expected_models.issubset(set(cfg.allowed_models)), (
        "Modèles manquants : " + ", ".join(expected_models - set(cfg.allowed_models))
    )
    # Échantillon d'actions ajoutées
    assert "action_set_won" in cfg.allowed_actions.get("crm.lead", [])
    assert "button_cancel" in cfg.allowed_actions.get("purchase.order", [])
    assert "action_send_mail" in cfg.allowed_actions.get("mailing.mailing", [])
    assert "action_pos_session_open" in cfg.allowed_actions.get("pos.session", [])
    assert "action_send" in cfg.allowed_actions.get("whatsapp.message", [])
    # Plafond et chemin d'audit inchangés
    assert cfg.mass_op_cap == 50
    assert cfg.audit_log_path == "audit.log"


def test_load_reads_readonly_models_and_frozen_fields(tmp_path, monkeypatch):
    for k, v in {
        "ODOO_URL": "https://x", "ODOO_DB": "db", "ODOO_USERNAME": "u",
        "ODOO_API_KEY": "k", "MCP_ACCESS_SECRET": "s",
    }.items():
        monkeypatch.setenv(k, v)
    toml = _write(tmp_path, """
[models]
allowed = ["marketing.campaign"]
readonly = ["ir.actions.server", "ir.model"]
[frozen_fields]
"marketing.campaign" = ["state"]
""")
    cfg = Config.load(toml_path=toml, env_path=str(tmp_path / "none.env"))
    assert cfg.readonly_models == ["ir.actions.server", "ir.model"]
    assert cfg.frozen_fields == {"marketing.campaign": ["state"]}


def test_load_defaults_when_sections_absent(tmp_path, monkeypatch):
    """Une config d'avant le pack marketing reste chargeable."""
    for k, v in {
        "ODOO_URL": "https://x", "ODOO_DB": "db", "ODOO_USERNAME": "u",
        "ODOO_API_KEY": "k", "MCP_ACCESS_SECRET": "s",
    }.items():
        monkeypatch.setenv(k, v)
    toml = _write(tmp_path, '[models]\nallowed = ["crm.lead"]\n')
    cfg = Config.load(toml_path=toml, env_path=str(tmp_path / "none.env"))
    assert cfg.readonly_models == []
    assert cfg.frozen_fields == {}


def test_example_config_ships_the_marketing_pack(monkeypatch, tmp_path):
    """Le gabarit du dépôt doit porter le pack Marketing Automation, et
    surtout ses garde-fous : aucune action sur marketing.campaign, `state`
    gelé, ir.actions.server en lecture seule."""
    for k, v in {
        "ODOO_URL": "https://x", "ODOO_DB": "db", "ODOO_USERNAME": "u",
        "ODOO_API_KEY": "k", "MCP_ACCESS_SECRET": "s",
    }.items():
        monkeypatch.setenv(k, v)
    cfg = Config.load(toml_path="config.example.toml",
                      env_path=str(tmp_path / "missing.env"))

    assert {"marketing.campaign", "marketing.activity"}.issubset(set(cfg.allowed_models))
    assert {"marketing.participant", "marketing.trace", "ir.model",
            "ir.model.fields", "ir.actions.server",
            "mailing.filter"}.issubset(set(cfg.readonly_models))
    # Les résultats et les actions serveur ne doivent surtout pas être en écriture.
    assert not set(cfg.readonly_models) & set(cfg.allowed_models)
    # Le lancement reste manuel : champ gelé ET aucune action de workflow.
    assert cfg.frozen_fields.get("marketing.campaign") == ["state"]
    assert cfg.allowed_actions.get("marketing.campaign") is None
