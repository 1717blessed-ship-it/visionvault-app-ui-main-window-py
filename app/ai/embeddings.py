def create_embedding(text: str) -> set[str]:
    """Representación local sencilla para búsquedas sin modelos externos."""
    return set(text.lower().split())
