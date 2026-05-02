from __future__ import annotations

import os
import time


def parse_document_job(workspace_name: str, document_path: str) -> dict[str, str]:
    return {
        "workspace": workspace_name,
        "document_path": document_path,
        "status": "queued_parser_placeholder",
    }


def evaluate_workspace_job(workspace_name: str) -> dict[str, str]:
    from pathlib import Path
    from workflow import run_workspace

    run_workspace(Path("workspaces") / workspace_name, Path("outputs") / workspace_name)
    return {"workspace": workspace_name, "status": "evaluated"}


def main() -> None:
    redis_url = os.getenv("REDIS_URL", "")
    print(f"Worker ready. REDIS_URL={redis_url or 'not configured'}")
    print("RQ/Celery queue wiring belongs here for production deployments.")
    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
