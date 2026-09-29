import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    import tomli as tomllib

_REQUIRED_ENV = ("ODOO_URL", "ODOO_DB", "ODOO_USERNAME", "ODOO_API_KEY", "MCP_ACCESS_SECRET")


@dataclass
class Config:
    odoo_url: str
    odoo_db: str
    odoo_username: str
    odoo_api_key: str
    access_secret: str
    allowed_models: list
    allowed_actions: dict
    mass_op_cap: int
    audit_log_path: str
    skills_dir: str
    # Modèles consultables mais jamais modifiables (création, écriture,
    # suppression et actions de workflow refusées).
    readonly_models: list = field(default_factory=list)
    # Champs dont l'écriture est refusée, par modèle. Sert à interdire les
    # bascules aux effets irréversibles (ex. lancer une campagne marketing).
    frozen_fields: dict = field(default_factory=dict)

    @classmethod
    def load(cls, toml_path="config.toml", env_path=".env"):
        if Path(env_path).exists():
            load_dotenv(env_path)
        missing = [k for k in _REQUIRED_ENV if not os.environ.get(k)]
        if missing:
            raise RuntimeError(
                "Variables d'environnement manquantes : " + ", ".join(missing)
            )
        data = {}
        if Path(toml_path).exists():
            data = tomllib.loads(Path(toml_path).read_text(encoding="utf-8"))
        guardrails = data.get("guardrails", {})
        return cls(
            odoo_url=os.environ["ODOO_URL"].rstrip("/"),
            odoo_db=os.environ["ODOO_DB"],
            odoo_username=os.environ["ODOO_USERNAME"],
            odoo_api_key=os.environ["ODOO_API_KEY"],
            access_secret=os.environ["MCP_ACCESS_SECRET"],
            allowed_models=list(data.get("models", {}).get("allowed", [])),
            readonly_models=list(data.get("models", {}).get("readonly", [])),
            allowed_actions={k: list(v) for k, v in data.get("actions", {}).items()},
            frozen_fields={k: list(v)
                           for k, v in data.get("frozen_fields", {}).items()},
            mass_op_cap=int(guardrails.get("mass_op_cap", 50)),
            audit_log_path=guardrails.get("audit_log_path", "audit.log"),
            skills_dir=data.get("skills", {}).get("dir", "skills_library"),
        )
