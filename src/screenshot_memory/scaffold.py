"""Side-effect-free description of the implemented scaffold boundary."""


def scaffold_status() -> dict[str, object]:
    """Report implemented capabilities without implying future features work."""
    return {
        "schema_version": 1,
        "stage": "local_core",
        "mode": "mock",
        "capabilities": {
            "status": True,
            "metadata_contracts": True,
            "storage_core": True,
            "deletion_core": True,
            "ranking_metrics": True,
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
        "message": (
            "Metadata, local storage/deletion and ranking metric core available; "
            "screenshot processing, retrieval and evaluation pending."
        ),
    }
