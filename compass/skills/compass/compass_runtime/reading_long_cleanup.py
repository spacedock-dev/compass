"""Explicit receipt release after marker retirement, never read-side recovery."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from . import annotations as annotation_store
from . import reading_long_jobs, reading_long_markers

if TYPE_CHECKING:
    from collections.abc import Callable

    from .config import RuntimeConfig
    from .state import RuntimeState


def release_receipt(
    config: RuntimeConfig,
    state: RuntimeState,
    *,
    job_id: str,
    header: Any,
    diagnostic_sink: Callable[[str], None] = print,
) -> str:
    """Release only after lstat proves absence under the marker publication lock.

    This neither acknowledges an outcome nor retires a marker. Lock order is
    marker then annotation. Future publication must use the same barrier and
    recheck the current marker before writing: an old loaded marker cannot
    authorize publication after its receipt has been released. Call this outside
    an already-held marker lock, which is deliberately not reentrant.
    """
    checked = reading_long_jobs.validate_header(header, job_id)
    if checked is None or (publication := checked.get("publication")) is None:
        return annotation_store.OUTCOME_REFUSED
    try:
        with reading_long_markers.publication_lock(config):
            try:
                reading_long_markers.marker_path(config, job_id).lstat()
            except FileNotFoundError:
                pass
            except OSError:
                return annotation_store.OUTCOME_REFUSED
            else:
                # Includes live, malformed, unreadable, and dangling symlink markers.
                return annotation_store.OUTCOME_REFUSED
            return annotation_store.release_long_receipt(
                config,
                state,
                publication["harness"],
                publication["sid"],
                job_id=job_id,
                incarnation=publication["incarnation"],
                diagnostic_sink=diagnostic_sink,
            )
    except OSError:
        return annotation_store.OUTCOME_UNWRITABLE
