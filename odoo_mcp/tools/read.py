from odoo_mcp.runtime import get_deps
from odoo_mcp.tools import mcp_tool


@mcp_tool
def server_status() -> dict:
    """Renvoie l'état de la connexion Odoo, les modèles modifiables, ceux
    consultables en lecture seule, et les champs gelés en écriture."""
    cfg = get_deps().config
    return {"odoo_url": cfg.odoo_url,
            "allowed_models": cfg.allowed_models,
            "readonly_models": cfg.readonly_models,
            "frozen_fields": cfg.frozen_fields}


@mcp_tool
def list_models() -> list:
    """Liste les modèles Odoo accessibles via ce serveur, en lecture comme en
    écriture. Certains sont en lecture seule : appelez server_status pour
    savoir lesquels avant de tenter une création ou une modification."""
    cfg = get_deps().config
    return cfg.allowed_models + [m for m in cfg.readonly_models
                                 if m not in cfg.allowed_models]


@mcp_tool
def inspect_model(model: str) -> dict:
    """Décrit les champs d'un modèle Odoo (nom, type, obligatoire, relation,
    valeurs de sélection). À utiliser avant toute création pour connaître les
    champs exacts."""
    return get_deps().odoo.fields(model)


@mcp_tool
def search(model: str, domain: list = None, fields: list = None,
           limit: int = 50, offset: int = 0, order: str = None) -> list:
    """Cherche des records. `domain` est un domaine Odoo (ex.
    [["name", "ilike", "acme"]]). Renvoie au plus `limit` records."""
    return get_deps().odoo.search(model, domain=domain, fields=fields,
                                  limit=limit, offset=offset, order=order)


@mcp_tool
def read(model: str, ids: list, fields: list = None) -> list:
    """Lit le détail des records dont les identifiants sont donnés."""
    return get_deps().odoo.read(model, ids, fields=fields)


@mcp_tool
def count(model: str, domain: list = None) -> int:
    """Compte les records correspondant au domaine, sans les télécharger."""
    return get_deps().odoo.count(model, domain=domain)


@mcp_tool
def stats(model: str, fields: list, groupby: list, domain: list = None) -> list:
    """Statistiques agrégées (regroupement). Ex. fields=["expected_revenue:sum"],
    groupby=["stage_id"]."""
    return get_deps().odoo.read_group(model, domain or [], fields, groupby)
