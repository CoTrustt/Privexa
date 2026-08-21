from __future__ import annotations

import subprocess
import sys


def test_clean_process_registers_every_sqlalchemy_mapper() -> None:
    """Production startup must not depend on test fixtures importing every model first."""

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from sqlalchemy.orm import configure_mappers; "
            "from privexa_api.main import create_app; "
            "assert create_app; "
            "configure_mappers()",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
