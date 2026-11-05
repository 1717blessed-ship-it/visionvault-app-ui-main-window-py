"""Preflight V1 puro/de solo lectura. No es un servicio de escritura ni una API.

No declara persistencia, autorización, revisión vigente o idempotencia consumada.
Esas garantías requieren el coordinador transaccional aún no habilitado.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json


class MobileOrderContractError(ValueError):
    def __init__(self, code: str, field: str, message: str, status: int = 422):
        super().__init__(message)
        self.code, self.field, self.status = code, field, status

    def response(self):
        return {"contract_version": 1, "persisted": False,
                "error": {"code": self.code, "field": self.field, "message": str(self)}}


def _fail(field, message="Campo inválido.", code="validation_failed"):
    raise MobileOrderContractError(code, field, message)


def _text(value, field, limit=120, required=True):
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        _fail(field)
    return value


def _integer(value, field, minimum=1, maximum=10000):
    if type(value) is not int or not minimum <= value <= maximum:
        _fail(field, "Se requiere un entero dentro del límite permitido.")


def _keys(value, allowed, field):
    if not isinstance(value, dict) or set(value) - allowed:
        _fail(field, "Objeto inválido o campos no admitidos.")


class MobileOrderContract:
    MAX_BYTES = 65536
    ROOT = {"contract_version", "operation_id", "client_order_id", "desktop_order_id",
            "expected_revision", "client", "whatsapp", "observations", "jobs"}
    JOB = {"client_job_id", "product_code", "variant_code", "material", "size",
           "quantity", "unit_kind", "notes", "designs"}
    DESIGN = {"association_id", "catalog_design_id", "quantity"}

    @classmethod
    def validate(cls, payload):
        _keys(payload, cls.ROOT, "payload")
        try:
            encoded = json.dumps(payload, allow_nan=False, ensure_ascii=False).encode("utf-8")
        except (ValueError, TypeError, UnicodeError, RecursionError):
            _fail("payload", "JSON no representable.")
        if len(encoded) > cls.MAX_BYTES:
            raise MobileOrderContractError("payload_too_large", "payload", "Solicitud demasiado grande.", 413)
        if type(payload.get("contract_version")) is not int or payload["contract_version"] != 1:
            _fail("contract_version", "Versión no admitida.")
        for key in ("operation_id", "client_order_id", "client"):
            _text(payload.get(key), key)
        _text(payload.get("whatsapp", ""), "whatsapp", 40, False)
        _text(payload.get("observations", ""), "observations", 2000, False)
        remote = payload.get("desktop_order_id")
        if remote is None:
            _integer(payload.get("expected_revision"), "expected_revision", 0, 0)
        else:
            _text(remote, "desktop_order_id", 20)
            if not remote.isascii() or not remote.isdigit() or int(remote) <= 0:
                _fail("desktop_order_id")
            _integer(payload.get("expected_revision"), "expected_revision", 1, 2**63-1)
        jobs = payload.get("jobs")
        if not isinstance(jobs, list) or not 1 <= len(jobs) <= 30:
            _fail("jobs", "Se requieren de 1 a 30 trabajos.")
        job_ids, association_ids = set(), set()
        for pos, job in enumerate(jobs):
            field = f"jobs[{pos}]"
            _keys(job, cls.JOB, field)
            for key in ("client_job_id", "product_code"):
                _text(job.get(key), field + "." + key)
            if job["client_job_id"] in job_ids:
                _fail(field + ".client_job_id", "Identidad duplicada.")
            job_ids.add(job["client_job_id"])
            for key, limit in (("variant_code", 120), ("material", 120), ("size", 40), ("notes", 2000)):
                _text(job.get(key, ""), field + "." + key, limit, False)
            _integer(job.get("quantity"), field + ".quantity")
            if job.get("unit_kind") not in ("item", "sheet"):
                _fail(field + ".unit_kind", "Unidad Desktop no admitida.")
            designs = job.get("designs")
            if not isinstance(designs, list) or len(designs) > 100:
                _fail(field + ".designs")
            design_ids, assigned = set(), 0
            for idx, design in enumerate(designs):
                name = f"{field}.designs[{idx}]"
                _keys(design, cls.DESIGN, name)
                _text(design.get("association_id"), name + ".association_id", 512)
                _text(design.get("catalog_design_id"), name + ".catalog_design_id", 256)
                if design["association_id"] in association_ids or design["catalog_design_id"] in design_ids:
                    _fail(name, "Asociación o diseño duplicado.")
                association_ids.add(design["association_id"])
                design_ids.add(design["catalog_design_id"])
                _integer(design.get("quantity"), name + ".quantity")
                assigned += design["quantity"]
            if assigned > job["quantity"]:
                _fail(field + ".designs", "La distribución supera la cantidad solicitada.")
        return deepcopy(payload)

    @classmethod
    def fingerprint(cls, payload):
        validated = cls.validate(payload)
        canonical = json.dumps(validated, sort_keys=True, separators=(",", ":"),
                               ensure_ascii=False, allow_nan=False).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    @classmethod
    def check_catalog(cls, connection, payload, resolve_design):
        """SELECT únicamente. El resolver debe ser el catálogo autorizado existente.

        No acepta rutas del cliente ni sustituye cotización/reservas/autorización.
        Esta lectura debe repetirse dentro de la futura transacción de escritura.
        """
        validated = cls.validate(payload)
        for pos, job in enumerate(validated["jobs"]):
            field = f"jobs[{pos}]"
            row = connection.execute("SELECT id FROM products WHERE code=? AND active=1",
                                     (job["product_code"],)).fetchone()
            if row is None:
                _fail(field + ".product_code", "Producto no disponible.", "product_invalid")
            if job.get("variant_code"):
                variant = connection.execute(
                    "SELECT id,material,size FROM product_variants WHERE code=? AND product_id=? AND active=1",
                    (job["variant_code"], row[0])).fetchone()
                if variant is None:
                    _fail(field + ".variant_code", "Variante no disponible.", "variant_invalid")
                for idx, attr in ((1, "material"), (2, "size")):
                    if variant[idx] and variant[idx] != job.get(attr, ""):
                        _fail(field + "." + attr, "La opción vigente no coincide.", "catalog_stale")
            for design in job["designs"]:
                if not resolve_design(design["catalog_design_id"]):
                    _fail(field + ".designs", "Diseño no disponible.", "design_not_found")
        return validated
