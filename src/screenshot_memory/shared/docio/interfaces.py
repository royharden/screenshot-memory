"""Injected ports; no source discovery, decoding, OCR engine or provider implementation."""

from typing import Protocol

from .models import Bounds, OcrResult, PageInput, PageSourceResult


class PageSource(Protocol):
    def pages(self, trusted_input: str, bounds: Bounds) -> PageSourceResult: ...


class OcrAdapter(Protocol):
    def recognize(self, page: PageInput, bounds: Bounds) -> OcrResult: ...


class VisionTextPort(Protocol):
    def recognize_asserted(self, page: PageInput, bounds: Bounds) -> OcrResult: ...
