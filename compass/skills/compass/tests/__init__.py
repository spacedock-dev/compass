import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
skill_path = str(SKILL_DIR)
if skill_path in sys.path:
    sys.path.remove(skill_path)
sys.path.insert(0, skill_path)

# Imported for the side effect, and imported here rather than from each test
# module because a module that forgot the import is exactly the case DRC-4431
# was: the leak came from classes that imported `support` and derived from a
# bare `unittest.TestCase` anyway. The path fix above has to land first.
from .support import forbid_live_update_checks, forbid_native_notifications  # noqa: E402

forbid_native_notifications()
forbid_live_update_checks()
