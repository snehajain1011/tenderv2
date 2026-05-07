import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def pytest_configure(config):
    import gstin_validator

    def clear_gstin_check(gstin: str):
        return gstin_validator.GstinCheck(
            gstin=gstin,
            legal_name="Test GSTIN",
            is_valid=True,
            is_active=True,
            check_status="clear",
            rejection_reason="",
        )

    gstin_validator.validate_gstin_api = clear_gstin_check
