"""Local workflow refusal type, independent of image and model libraries."""

from screenshot_memory.shared.vindex import StoreError


class WorkflowError(StoreError):
    def __init__(self, reason: str, cleanup=()):
        super().__init__(reason)
        self.cleanup = cleanup
