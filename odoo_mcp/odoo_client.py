import xmlrpc.client


class OdooError(Exception):
    pass


# Seules ces méthodes comptent comme de la lecture. Tout le reste — y compris
# les actions de workflow appelées par leur nom — est traité comme une
# écriture. Refus par défaut : une méthode ajoutée demain sera considérée
# comme dangereuse tant qu'elle n'est pas inscrite ici explicitement.
_READ_METHODS = frozenset({
    "search_read", "read", "fields_get", "search_count", "read_group",
})


def _clean_fault(fault_string):
    lines = [l for l in (fault_string or "").splitlines() if l.strip()]
    return lines[-1].strip() if lines else "Erreur Odoo inconnue"


class OdooClient:
    def __init__(self, url, db, username, api_key, allowed_models,
                 readonly_models=None, frozen_fields=None):
        self.url = url.rstrip("/")
        self.db = db
        self.username = username
        self.api_key = api_key
        self.allowed_models = set(allowed_models)
        self.readonly_models = set(readonly_models or ())
        self.frozen_fields = {model: set(fields)
                              for model, fields in (frozen_fields or {}).items()}
        self._uid = None
        self._common = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/common")
        self._models = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/object")

    def _ensure_uid(self):
        if self._uid is None:
            try:
                uid = self._common.authenticate(self.db, self.username, self.api_key, {})
            except (xmlrpc.client.ProtocolError, ConnectionError, OSError) as exc:
                raise OdooError(f"Odoo injoignable : {exc}") from exc
            if not uid:
                raise OdooError(
                    "Authentification Odoo échouée : clé API ou identifiants invalides."
                )
            self._uid = uid
        return self._uid

    def _check_model(self, model, write):
        if model in self.allowed_models:
            return
        if model in self.readonly_models:
            if not write:
                return
            raise OdooError(
                f"Modèle '{model}' accessible en lecture seule : création, "
                f"modification, suppression et actions y sont refusées. "
                f"Faites la modification à la main dans Odoo."
            )
        raise OdooError(
            f"Modèle '{model}' non autorisé. Modèles autorisés : "
            + ", ".join(sorted(self.allowed_models | self.readonly_models))
        )

    def _check_frozen_fields(self, model, values):
        """Refuse l'écriture des champs gelés : ceux dont la modification a des
        effets qu'on ne peut pas rattraper (ex. faire passer une campagne
        marketing en « running », ce qui déclenche de vrais envois)."""
        frozen = self.frozen_fields.get(model)
        if not frozen or not isinstance(values, dict):
            return
        touched = sorted(frozen & set(values))
        if touched:
            raise OdooError(
                f"Champ(s) {', '.join(touched)} de '{model}' non modifiable(s) "
                f"via le connecteur : cette bascule a des effets irréversibles "
                f"et se fait à la main dans Odoo."
            )

    def execute_kw(self, model, method, args, kwargs=None):
        self._check_model(model, write=method not in _READ_METHODS)
        uid = self._ensure_uid()
        attempts = 0
        while True:
            attempts += 1
            try:
                return self._models.execute_kw(
                    self.db, uid, self.api_key, model, method, args, kwargs or {}
                )
            except xmlrpc.client.Fault as exc:
                raise OdooError(_clean_fault(exc.faultString)) from exc
            except (xmlrpc.client.ProtocolError, ConnectionError, OSError) as exc:
                if attempts >= 2:
                    raise OdooError(f"Odoo injoignable : {exc}") from exc

    def search(self, model, domain=None, fields=None, limit=None, offset=0, order=None):
        kwargs = {"fields": fields or []}
        if limit is not None:
            kwargs["limit"] = limit
        if offset:
            kwargs["offset"] = offset
        if order:
            kwargs["order"] = order
        return self.execute_kw(model, "search_read", [domain or []], kwargs)

    def read(self, model, ids, fields=None):
        return self.execute_kw(model, "read", [list(ids)], {"fields": fields or []})

    def fields(self, model):
        return self.execute_kw(model, "fields_get", [], {
            "attributes": ["string", "type", "required", "selection", "relation"]
        })

    def count(self, model, domain=None):
        return self.execute_kw(model, "search_count", [domain or []])

    def read_group(self, model, domain, fields, groupby):
        return self.execute_kw(model, "read_group", [domain or [], fields, groupby])

    def create(self, model, values):
        self._check_frozen_fields(model, values)
        return self.execute_kw(model, "create", [values])

    def write(self, model, ids, values):
        self._check_frozen_fields(model, values)
        return self.execute_kw(model, "write", [list(ids), values])

    def unlink(self, model, ids):
        return self.execute_kw(model, "unlink", [list(ids)])

    def call_action(self, model, ids, action):
        return self.execute_kw(model, action, [list(ids)])

    def post_message(self, model, record_id, body):
        return self.execute_kw(model, "message_post", [[record_id]], {
            "body": body,
            "message_type": "comment",
        })

    def send_email(self, model, record_id, partner_ids, subject, body):
        return self.execute_kw(model, "message_post", [[record_id]], {
            "subject": subject,
            "body": body,
            "partner_ids": list(partner_ids),
            "message_type": "comment",
            "subtype_xmlid": "mail.mt_comment",
        })
