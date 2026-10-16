"""Typed synthetic OCR controls, actual Pillow/SQLite/publication/FTS/deletion."""

import hashlib
import importlib.abc
import json
import sys
from collections.abc import Callable
from dataclasses import replace

import pytest
from PIL import Image

from screenshot_memory import workflow
from screenshot_memory.adapters.ocr import (
    EngineIdentity,
    EngineLine,
    EnginePage,
    EngineWord,
    OcrEngineError,
    StoreOcrAdapter,
)
from screenshot_memory.adapters.rapidocr import LocalModels, RapidOcrEngine
from screenshot_memory.contracts import StageStatus
from screenshot_memory.image_source import GRID_POLICY
from screenshot_memory.keyword_query import query_keywords
from screenshot_memory.regions import (
    ARTIFACT_ROW,
    DECODE_ROW,
    DOCUMENT_ROW,
    DecodedGrid,
    PillowSourceGridDecoder,
    install_screenshot_resolver,
    literal_line_pointer,
)
from screenshot_memory.shared.cited.models import ArtifactRef, ResolutionContext, ScreenshotPointer
from screenshot_memory.shared.cited.registry import Registry
from screenshot_memory.shared.docio.identity import canonical_bytes
from screenshot_memory.shared.docio.interfaces import OcrAdapter
from screenshot_memory.shared.docio.models import (
    Bounds,
    Document,
    PageSourceResult,
    ProcessingArtifact,
)
from screenshot_memory.shared.vindex import Deleter, GenerationToken, Store
from screenshot_memory.shared.vindex.deletion import STORES
from screenshot_memory.shared.vindex.search import keyword_search

QUAD = ((2.0, 2.0), (12.0, 2.0), (12.0, 8.0), (2.0, 8.0))
WORD = EngineWord("Café", None, QUAD)
LINE = EngineLine("Café", 0.73, QUAD, (WORD,))
DEFAULT_PAGE = EnginePage((LINE,))


@pytest.fixture(autouse=True)
def deny_native_SDK_imports():
    forbidden = {"rapidocr", "onnxruntime", "numpy", "cv2", "omegaconf"}
    assert not forbidden.intersection(sys.modules), "native SDK unexpectedly preloaded"

    class NoSDK(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path, target=None):
            if fullname.split(".")[0] in forbidden:
                raise AssertionError("native SDK/model execution not granted by these tests")

    guard = NoSDK()
    sys.meta_path.insert(0, guard)
    yield
    sys.meta_path.remove(guard)


class ControlledEngine:
    identity = EngineIdentity("synthetic-ocr-control", "1", "d" * 64, GRID_POLICY, "synthetic")

    def __init__(self, output: EnginePage = DEFAULT_PAGE):
        self.output = output
        self.calls = 0
        self.on_call: Callable[[], None] = lambda: None

    def recognize(self, rgba8: bytes, width: int, height: int, bounds: Bounds) -> EnginePage:
        assert len(rgba8) == width * height * 4 and (width, height) == (32, 20)
        self.calls += 1
        self.on_call()
        return self.output


class IssuedControl:
    def __init__(self, token: GenerationToken):
        self.token = token
        self.refs = tuple(
            ArtifactRef(artifact_id=n, artifact_sha256=d * 64, profile_id="typed-control/1")
            for n, d in (("access", "a"), ("issued", "b"))
        )

    def policy_refs(self) -> tuple[ArtifactRef, ArtifactRef]:
        return self.refs

    def issued_token(
        self, pointer: ScreenshotPointer, context: ResolutionContext
    ) -> GenerationToken:
        return self.token


def setup(tmp_path):
    path = tmp_path / "anonymous.png"
    with Image.new("RGB", (32, 20), "white") as image:
        image.save(path)
    store = Store(tmp_path / "private")
    cid = workflow.create_collection(store)
    (item,) = workflow.import_images(store, cid, (path,))
    token = store.token(cid, item.item_id)
    source = PageSourceResult.model_validate_json(store.get("content", token, DECODE_ROW))
    return store, cid, item, token, source.pages[0], path


def bounds(**updates):
    values = dict(
        max_pages=1,
        max_encoded_bytes=1024 * 1024,
        max_decoded_pixels=1024,
        max_words=4,
        max_lines=4,
        max_blocks=1,
        max_output_bytes=65536,
        deadline_s=2.0,
    )
    return Bounds(**(values | updates))


def no_ocr_rows(store):
    with store.connection() as conn:
        assert conn.execute("SELECT count(*) FROM content").fetchone()[0] == 1
        for table in ("words", "lines", "item_fts", "line_fts"):
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0


def test_canonical_port_publish_literal_resolve_and_every_new_projection_deleted(tmp_path):
    store, cid, item, token, page, path = setup(tmp_path)
    engine = ControlledEngine()
    adapter: OcrAdapter = StoreOcrAdapter(store, token, PillowSourceGridDecoder(), engine)
    result = adapter.recognize(page, bounds())
    assert result.status == "ok" and result.page.lines[0].text == "Café"
    assert result.page.words[0].ocr_confidence is None
    assert result.page.lines[0].ocr_confidence == 0.73
    current = store.item(token)
    assert current.revision == 2 and current.stages[1].provenance == "synthetic"
    artifact_raw = store.get("content", token, ARTIFACT_ROW)
    artifact = ProcessingArtifact.model_validate_json(artifact_raw)
    assert hashlib.sha256(artifact_raw).hexdigest() == current.evidence_artifact_sha256
    assert artifact.artifact_id == result.processing_artifact_ref
    document = Document.model_validate_json(store.get("content", token, DOCUMENT_ROW))
    assert document.provenance.producer == "synthetic-ocr-control"
    with store.connection() as conn:
        for table in ("words", "lines", "item_fts", "line_fts"):
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 1
    assert keyword_search(store, cid, "cafe")[0].token == token
    pointer = literal_line_pointer(document, artifact_raw, "Café")
    registry = Registry()
    access = IssuedControl(token)
    context = ResolutionContext(
        namespace_id=cid,
        access_policy_ref=access.refs[0],
        generation_policy_ref=access.refs[1],
        required_scope="text_and_spatial",
    )
    install_screenshot_resolver(registry, store, access, PillowSourceGridDecoder())
    assert registry.resolve(pointer, context).excerpt == "Café"
    assert adapter.recognize(page, bounds()).issues == ("ocr_output_immutable",)
    assert engine.calls == 1
    receipt = Deleter(store).delete(cid, item.item_id)
    assert receipt.status == "deleted" and receipt.stores_verified == STORES
    with store.connection() as conn:
        assert all(conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] == 0 for t in STORES)
    assert keyword_search(store, cid, "cafe") == ()
    assert registry.resolve(pointer, context).status == "stale"
    assert path.is_file()


@pytest.mark.parametrize("confirmed,expected", [(True, "ok"), (False, "unavailable")])
def test_successful_blank_is_distinct_from_missing_recognition(tmp_path, confirmed, expected):
    store, cid, _, token, page, _ = setup(tmp_path)
    engine = ControlledEngine(EnginePage((), confirmed_blank=confirmed))
    result = StoreOcrAdapter(store, token, PillowSourceGridDecoder(), engine).recognize(
        page, bounds()
    )
    assert result.status == expected
    assert keyword_search(store, cid, "anything") == ()
    # Real publication must retain enough evidence to distinguish an empty
    # successful result from an engine that supplied no observation.
    keyword = query_keywords(Store(store.root), cid, "anything")
    assert keyword["status"] == expected and keyword["executed"] is confirmed
    assert keyword["coverage"] == {
        "visible_items": 1,
        "indexed_items": 0,
        "empty_ocr_items": int(confirmed),
        "unindexed_items": int(not confirmed),
    }
    if confirmed:
        assert result.page.words == () and result.page.lines == ()
        assert store.item(token).stages[1].status == "ready"
    else:
        assert result.page is None
        no_ocr_rows(store)


@pytest.mark.parametrize("kind", ["foreign", "generation", "bytes", "decode_record", "profile"])
def test_source_and_generation_refuse_before_engine_call(tmp_path, kind):
    store, _, item, token, page, _ = setup(tmp_path)
    engine = ControlledEngine()
    if kind == "foreign":
        page = page.model_copy(update={"page_id": "foreign-page"})
    elif kind == "generation":
        token = token.model_copy(update={"collection_generation": token.collection_generation + 1})
    elif kind == "bytes":
        store.object_path(token.collection_id, token.item_id, item.source_object_id).write_bytes(
            b"bad"
        )
    elif kind == "decode_record":
        store.put("content", token, DECODE_ROW, b"{}")
    else:
        engine.identity = replace(engine.identity, source_grid_profile="other-profile/1")
    result = StoreOcrAdapter(store, token, PillowSourceGridDecoder(), engine).recognize(
        page, bounds()
    )
    assert result.status == "invalid" and result.page is None and engine.calls == 0
    no_ocr_rows(store)


def test_wrong_recomputed_grid_refuses_before_engine(tmp_path):
    store, _, _, token, page, _ = setup(tmp_path)

    class WrongGrid(PillowSourceGridDecoder):
        def decode(self, raw):
            return DecodedGrid(32, 20, b"\0" * (32 * 20 * 4))

    engine = ControlledEngine()
    result = StoreOcrAdapter(store, token, WrongGrid(), engine).recognize(page, bounds())
    assert result.status == "invalid" and engine.calls == 0
    no_ocr_rows(store)


@pytest.mark.parametrize("limit", [{"max_encoded_bytes": 1}, {"max_decoded_pixels": 1}])
def test_source_budget_precedes_engine(tmp_path, limit):
    store, _, _, token, page, _ = setup(tmp_path)
    engine = ControlledEngine()
    result = StoreOcrAdapter(store, token, PillowSourceGridDecoder(), engine).recognize(
        page, bounds(**limit)
    )
    assert result.status == "limit_exceeded" and engine.calls == 0
    no_ocr_rows(store)


@pytest.mark.parametrize(
    "output,limits,status",
    [
        (EnginePage((LINE, LINE)), {"max_lines": 1}, "limit_exceeded"),
        (EnginePage((replace(LINE, words=(WORD, WORD)),)), {"max_words": 1}, "limit_exceeded"),
        (EnginePage((LINE,)), {"max_output_bytes": 1}, "limit_exceeded"),
        (EnginePage((LINE,)), {"max_output_bytes": 1024}, "limit_exceeded"),
        (EnginePage((replace(LINE, words=()),)), {}, "invalid"),
        (EnginePage((replace(LINE, score=float("nan")),)), {}, "invalid"),
        (EnginePage((replace(LINE, quad=((2.0, 2.0),) * 4),)), {}, "invalid"),
        (EnginePage((LINE,), confirmed_blank=True), {}, "invalid"),
    ],
)
def test_invalid_or_over_budget_observation_publishes_nothing(tmp_path, output, limits, status):
    store, _, _, token, page, _ = setup(tmp_path)
    engine = ControlledEngine(output)
    result = StoreOcrAdapter(store, token, PillowSourceGridDecoder(), engine).recognize(
        page, bounds(**limits)
    )
    assert result.status == status and result.page is None
    assert store.item(token).revision == 1
    no_ocr_rows(store)


def test_native_error_and_expired_output_are_never_published_as_blank(tmp_path):
    store, _, _, token, page, _ = setup(tmp_path)
    engine = ControlledEngine()

    def fail():
        raise OcrEngineError("controlled-native-failure")

    engine.on_call = fail
    adapter = StoreOcrAdapter(store, token, PillowSourceGridDecoder(), engine)
    assert adapter.recognize(page, bounds()).status == "unavailable"
    now = [0.0]
    adapter._clock = lambda: now[0]
    engine.on_call = lambda: now.__setitem__(0, 10.0)
    assert adapter.recognize(page, bounds()).status == "timeout"
    no_ocr_rows(store)


def test_delete_during_compute_cannot_resurrect_or_release_page(tmp_path):
    store, cid, item, token, page, _ = setup(tmp_path)
    engine = ControlledEngine()
    engine.on_call = lambda: Deleter(store).delete(cid, item.item_id)
    result = StoreOcrAdapter(store, token, PillowSourceGridDecoder(), engine).recognize(
        page, bounds()
    )
    assert result.status == "invalid" and result.page is None
    with store.connection() as conn:
        assert all(conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] == 0 for t in STORES)


def test_other_stage_revision_wins_and_is_not_overwritten(tmp_path):
    store, _, _, token, page, _ = setup(tmp_path)
    engine = ControlledEngine()

    def other_writer():
        current = store.item(token)
        caption = StageStatus(
            stage="caption",
            status="ready",
            item_generation=0,
            processing_revision="synthetic-caption/1",
            result_sha256="a" * 64,
            provenance="synthetic",
        )
        following = current.model_copy(
            update={"revision": 2, "stages": (*current.stages[:2], caption, *current.stages[3:])}
        )
        store.publish_stage(token, 1, "caption", following, (("captions", "b" * 32, b"control"),))

    engine.on_call = other_writer
    result = StoreOcrAdapter(store, token, PillowSourceGridDecoder(), engine).recognize(
        page, bounds()
    )
    assert result.status == "invalid" and result.page is None
    assert store.item(token).stages[2].status == "ready"
    assert store.item(token).stages[1].status == "not_run"
    no_ocr_rows(store)


def test_mid_publication_SQL_failure_rolls_back_all_ocr_rows(tmp_path):
    store, _, _, token, page, _ = setup(tmp_path)
    with store.transaction() as conn:
        conn.execute(
            "CREATE TRIGGER fail_lines BEFORE INSERT ON lines "
            "BEGIN SELECT RAISE(ABORT,'control'); END"
        )
    result = StoreOcrAdapter(store, token, PillowSourceGridDecoder(), ControlledEngine()).recognize(
        page, bounds()
    )
    assert result.status != "ok" and result.page is None and store.item(token).revision == 1
    no_ocr_rows(store)


def test_model_configuration_is_lazy_path_independent_and_cannot_drift(tmp_path):
    first = RapidOcrEngine(LocalModels(tmp_path / "d", tmp_path / "c", tmp_path / "r"))
    second = RapidOcrEngine(
        LocalModels(tmp_path / "else-d", tmp_path / "else-c", tmp_path / "else-r")
    )
    assert first.identity == second.identity and first._engine is None
    assert canonical_bytes(json.loads(first.config_bytes)) == first.config_bytes
    with pytest.raises(TypeError):
        first.parameters["Global.use_preprocess_img"] = True
    for path in first.models.paths().values():
        path.write_bytes(b"not a model")
    with pytest.raises(OcrEngineError):
        first.recognize(b"\xff" * 16, 2, 2, bounds())
    assert first._engine is None


def test_native_backend_lock_timeout_does_not_load_models(tmp_path):
    engine = RapidOcrEngine(LocalModels(tmp_path / "d", tmp_path / "c", tmp_path / "r"))
    engine._lock.acquire()
    try:
        with pytest.raises(TimeoutError):
            engine.recognize(b"\xff" * 16, 2, 2, bounds(deadline_s=0.001))
    finally:
        engine._lock.release()
    assert engine._engine is None


def test_backend_identity_cannot_change_between_snapshot_and_publication(tmp_path):
    store, _, _, token, page, _ = setup(tmp_path)
    engine = ControlledEngine()

    def change_identity():
        engine.identity = replace(engine.identity, config_sha256="e" * 64)

    engine.on_call = change_identity
    result = StoreOcrAdapter(store, token, PillowSourceGridDecoder(), engine).recognize(
        page, bounds()
    )
    assert result.status == "invalid" and result.issues == ("engine_identity_changed",)
    no_ocr_rows(store)
