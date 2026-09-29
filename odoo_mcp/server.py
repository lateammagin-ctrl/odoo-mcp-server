import os

from odoo_mcp import runtime
from odoo_mcp.auth import extract_bearer, verify_secret
from odoo_mcp.config import Config
from odoo_mcp.odoo_client import OdooClient
from odoo_mcp.tools import all_tools
from odoo_mcp.tools import actions, read, write  # noqa: F401  (enregistre les outils)


def is_authorized(authorization_header, query_secret, expected_secret):
    """Vrai si le bon secret partagé est fourni — soit dans l'en-tête
    Authorization (Bearer), soit dans le paramètre d'URL `secret`.
    Le paramètre d'URL permet de brancher le connecteur Claude, dont
    l'écran de configuration n'offre pas de champ « jeton »."""
    provided = extract_bearer(authorization_header) or query_secret
    return verify_secret(provided, expected_secret)


def build_app():
    """Construit l'application ASGI : FastMCP (HTTP streamable) + middleware
    d'authentification par secret partagé. Le endpoint /health reste ouvert."""
    from fastmcp import FastMCP
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse

    cfg = Config.load(
        toml_path=os.environ.get("ODOO_MCP_CONFIG", "config.toml"),
        env_path=os.environ.get("ODOO_MCP_ENV", ".env"),
    )
    runtime.deps = runtime.Deps(
        config=cfg,
        odoo=OdooClient(cfg.odoo_url, cfg.odoo_db, cfg.odoo_username,
                        cfg.odoo_api_key, cfg.allowed_models,
                        readonly_models=cfg.readonly_models,
                        frozen_fields=cfg.frozen_fields),
    )

    mcp = FastMCP("Odoo MCP — magin")
    for fn in all_tools():
        mcp.tool(fn)

    # FastMCP 3.x : http_app() renvoie une application Starlette (transport
    # streamable-http). Voir https://gofastmcp.com si l'API évolue.
    app = mcp.http_app()

    class AuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            if request.url.path == "/health":
                return JSONResponse({"status": "ok"})
            if not is_authorized(request.headers.get("authorization"),
                                 request.query_params.get("secret"),
                                 cfg.access_secret):
                return JSONResponse({"error": "non autorisé"}, status_code=401)
            return await call_next(request)

    app.add_middleware(AuthMiddleware)
    return app


def main():
    import uvicorn
    app = build_app()
    uvicorn.run(app, host="127.0.0.1",
                port=int(os.environ.get("ODOO_MCP_PORT", "8000")))


if __name__ == "__main__":
    main()
