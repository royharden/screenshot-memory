"""Explicit local RapidOCR backend. No SDK import or model construction on import."""

import hashlib
import importlib
import importlib.metadata
import stat
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from screenshot_memory.adapters.ocr import (
    EngineIdentity,
    EngineLine,
    EnginePage,
    EngineWord,
    OcrEngineError,
)
from screenshot_memory.image_source import GRID_POLICY, POLICY_SHA
from screenshot_memory.shared.docio.identity import canonical_bytes
from screenshot_memory.shared.docio.models import Bounds

MODELS = MappingProxyType(
    {
        "Det": (9929594, "090f04abcd9d9a7498bc4ebf677e4cb9bdce1fe4197ddb7e529f1ef44e1ff94f"),
        "Cls": (585532, "e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c"),
        "Rec": (21234383, "6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884"),
    }
)
VERSIONS = MappingProxyType(
    {
        "rapidocr": "3.10.0",
        "onnxruntime": "1.31.0",
        "numpy": "2.5.4",
        "opencv-python-headless": "5.0.0.93",
        "omegaconf": "2.4.0",
        "Pillow": "10.4.0",
    }
)


@dataclass(frozen=True, slots=True)
class LocalModels:
    detector: Path
    classifier: Path
    recognizer: Path

    def paths(self) -> dict[str, Path]:
        return {
            "Det": Path(self.detector),
            "Cls": Path(self.classifier),
            "Rec": Path(self.recognizer),
        }


def _verified_model(path: Path, size: int, digest: str) -> bytes:
    """Hash the exact bounded bytes later passed to ORT, avoiding a second path read."""
    if ".." in path.parts:
        raise OcrEngineError("invalid_model_path")
    path = path.absolute()
    if any(p.is_symlink() or p.is_junction() for p in (path, *path.parents)):
        raise OcrEngineError("invalid_model_path")
    if not stat.S_ISREG(path.stat().st_mode) or path.stat().st_size != size:
        raise OcrEngineError("model_size_mismatch")
    with path.open("rb") as stream:
        raw = stream.read(size + 1)
    if len(raw) != size or hashlib.sha256(raw).hexdigest() != digest:
        raise OcrEngineError("model_hash_mismatch")
    return raw


class _CountedSession:
    """Observe successful native detector calls without replacing their output."""

    def __init__(self, delegate):
        self.delegate = delegate
        self.completed_calls = 0

    def __call__(self, *args, **kwargs):
        result = self.delegate(*args, **kwargs)
        self.completed_calls += 1
        return result

    def __getattr__(self, name):
        return getattr(self.delegate, name)


class RapidOcrEngine:
    """Lazy CPU-only engine for the exact supported local model/config edition.

    Caller owns rights/provenance qualification and process deadlines. No package
    installation, model discovery, download, visualizer or fallback is provided.
    Provided ORT sessions avoid the SDK's default model acquisition branch; the
    recognition dictionary must be embedded in the verified model metadata.
    """

    def __init__(self, models: LocalModels):
        if not isinstance(models, LocalModels):
            raise TypeError("explicit_local_models_required")
        self.models = models
        self.parameters = MappingProxyType(
            {
                "Global.use_preprocess_img": False,
                "Global.use_vertical_padding": False,
                "Global.return_word_box": True,
                "Global.return_single_char_box": False,
                "Global.text_score": 0.5,
                "Det.limit_side_len": 640,
                "Det.limit_type": "max",
                "EngineConfig.onnxruntime.use_cuda": False,
                "EngineConfig.onnxruntime.use_dml": False,
                "EngineConfig.onnxruntime.use_cann": False,
                "EngineConfig.onnxruntime.use_coreml": False,
            }
        )
        config = {
            "algorithm": "s7-rapidocr-provided-sessions/1",
            "versions": dict(VERSIONS),
            "models": {key: {"bytes": size, "sha256": sha} for key, (size, sha) in MODELS.items()},
            "parameters": dict(self.parameters),
            "source_grid_profile": GRID_POLICY,
            "source_decode_config_sha256": POLICY_SHA,
            "alpha": "RGBA8-over-white-rounded/1",
            "provider": "CPUExecutionProvider",
            "intra_op_threads": 2,
            "inter_op_threads": 1,
            "thread_spinning": False,
            "opencv_threads": 2,
        }
        self.config_bytes = canonical_bytes(config)
        self.identity = EngineIdentity(
            producer="RapidOCR-ORT-CPU",
            version="3.10.0+ort1.31.0",
            config_sha256=hashlib.sha256(self.config_bytes).hexdigest(),
            source_grid_profile=GRID_POLICY,
            provenance="observed",
        )
        self._engine = None
        self._lock = threading.Lock()

    def _load(self):
        if self._engine is not None:
            return
        raw_models = {
            key: _verified_model(path, *MODELS[key]) for key, path in self.models.paths().items()
        }
        try:
            for name, version in VERSIONS.items():
                if importlib.metadata.version(name) != version:
                    raise OcrEngineError("native_dependency_version_mismatch")
            ort = importlib.import_module("onnxruntime")
            cv2 = importlib.import_module("cv2")
            sdk = importlib.import_module("rapidocr")
            omega = importlib.import_module("omegaconf")
            ort.disable_telemetry_events()
            cv2.setNumThreads(2)
            sessions = {}
            for key, raw in raw_models.items():
                opts = ort.SessionOptions()
                opts.intra_op_num_threads = 2
                opts.inter_op_num_threads = 1
                opts.enable_cpu_mem_arena = False
                opts.add_session_config_entry("session.intra_op.allow_spinning", "0")
                opts.add_session_config_entry("session.inter_op.allow_spinning", "0")
                session = ort.InferenceSession(
                    raw, sess_options=opts, providers=["CPUExecutionProvider"]
                )
                if session.get_providers() != ["CPUExecutionProvider"]:
                    raise OcrEngineError("native_provider_mismatch")
                sessions[key] = session
            if not sessions["Rec"].get_modelmeta().custom_metadata_map.get("character"):
                raise OcrEngineError("embedded_character_dictionary_missing")
            parameters = dict(self.parameters)
            parameters.update(
                {f"{key}.model_path": str(p.absolute()) for key, p in self.models.paths().items()}
            )
            engine = sdk.RapidOCR(params=parameters)
            # This instance-local, supported SDK session seam avoids global patching.
            for key, session in sessions.items():
                with omega.flag_override(engine.cfg[key], "allow_objects", True):
                    engine.cfg[key].session = session
            engine._load_det_model()
            engine._load_cls_model()
            engine._load_rec_model()
            engine.text_det.session = _CountedSession(engine.text_det.session)
            self._engine = engine
        except OcrEngineError:
            raise
        except Exception:
            raise OcrEngineError("native_runtime_unavailable") from None

    def recognize(self, rgba8: bytes, width: int, height: int, bounds: Bounds) -> EnginePage:
        if (
            type(rgba8) is not bytes
            or type(width) is not int
            or type(height) is not int
            or min(width, height) <= 0
            or width * height > bounds.max_decoded_pixels
            or len(rgba8) != width * height * 4
        ):
            raise OcrEngineError("invalid_source_grid")
        started = time.monotonic()
        if not self._lock.acquire(timeout=bounds.deadline_s):
            raise TimeoutError
        try:
            self._load()
            if time.monotonic() - started > bounds.deadline_s:
                raise TimeoutError
            np = importlib.import_module("numpy")
            main = importlib.import_module("rapidocr.main")
            rgba = np.frombuffer(rgba8, dtype=np.uint8).reshape(height, width, 4).astype(np.uint16)
            alpha = rgba[:, :, 3:4]
            rgb = ((rgba[:, :, :3] * alpha + 255 * (255 - alpha) + 127) // 255).astype(np.uint8)
            original = rgb[:, :, ::-1].copy()
            engine = self._engine
            image, operations = engine.preprocess_img(original)
            before = engine.text_det.session.completed_calls
            try:
                crops, detected = engine.detect_and_crop(image, operations)
            except main.RapidOCRError as error:
                if (
                    str(error) == "The text detection result is empty"
                    and engine.text_det.session.completed_calls == before + 1
                ):
                    return EnginePage((), confirmed_blank=True)
                raise OcrEngineError("detection_unavailable") from None
            classified_images, classified = engine.cls_and_rotate(crops)
            recognized = engine.recognize_txt(classified_images)
            result = engine.build_final_output(
                original, detected, classified, recognized, crops, operations
            )
            if result.txts is None or not len(result.txts):
                raise OcrEngineError("recognition_unavailable")
            if len(result.txts) > bounds.max_lines:
                raise OcrEngineError("native_line_limit_exceeded")

            def quad(value):
                return tuple(tuple(float(v) for v in point) for point in value)

            lines = []
            for i, text in enumerate(result.txts):
                words = tuple(
                    EngineWord(str(word), None if score is None else float(score), quad(box))
                    for word, score, box in result.word_results[i]
                    if box is not None
                )
                if not words:
                    raise OcrEngineError("word_geometry_unavailable")
                lines.append(
                    EngineLine(str(text), float(result.scores[i]), quad(result.boxes[i]), words)
                )
            if time.monotonic() - started > bounds.deadline_s:
                raise TimeoutError
            return EnginePage(tuple(lines))
        except (OcrEngineError, TimeoutError):
            raise
        except Exception:
            raise OcrEngineError("native_recognition_unavailable") from None
        finally:
            self._lock.release()
