"""Side-effect-free description of the implemented scaffold boundary."""


def scaffold_status() -> dict[str, object]:
    """Report implemented capabilities without implying future features work."""
    return {
        "schema_version": 1,
        "stage": "scaffold",
        "mode": "mock",
        "capabilities": {
            "status": True,
            "ingest": False,
            "ocr": False,
            "caption": False,
            "text_embeddings": False,
            "image_embeddings": False,
            "search": False,
            "regions": False,
            "delete": False,
            "evaluation": False,
        },
        "feature_provenance": "none",
        "items": [],
        "hits": [],
        "message": "Scaffold only; no screenshots, model output or retrieval measurements.",
    }
