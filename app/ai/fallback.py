"""Ejecución tolerante a fallos de los analizadores de imágenes."""

from __future__ import annotations

from typing import Callable

from app.ai.result import has_usable_analysis


def analyze_image_with_fallback(
    path: str,
    provider: str,
    gemini_api_key: str,
    gemini_model: str,
    progress: Callable[[str], None] | None = None,
) -> dict:
    """Usa Gemini cuando está disponible y continúa con IA local si falla."""
    progress = progress or (lambda _message: None)
    remote_errors: list[str] = []

    if provider == "Gemini":
        from app.ai.gemini import analyze_image as analyze_gemini

        remote_result = analyze_gemini(path, gemini_api_key, gemini_model, progress)
        if has_usable_analysis(remote_result):
            return remote_result | {"provider_used": "Gemini"}
        remote_errors = list(remote_result.get("errors") or [])
        if remote_result.get("missing"):
            remote_errors.append("Gemini no está configurado.")
        progress("Gemini no devolvió datos; probando IA local…")
    else:
        progress("Analizando con IA local…")

    from app.ai.analyzer import analyze_image as analyze_local

    local_result = analyze_local(path, progress)
    if has_usable_analysis(local_result):
        return local_result | {"provider_used": "IA local"}

    errors = remote_errors + list(local_result.get("errors") or [])
    if not errors:
        errors.append("Ningún motor de IA pudo identificar contenido en esta imagen.")
    return local_result | {"errors": errors, "provider_used": "IA local"}
