"""Run the end-to-end pipeline in order.

    generate -> clean/validate -> load PostgreSQL -> SQL reports -> analysis metrics

Usage:
    python -m src.pipeline              # full pipeline (needs `docker compose up -d` first)
    python -m src.pipeline --skip-db    # Python-only: data, cleaning and analysis metrics
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time

STAGES: tuple[tuple[str, str, bool], ...] = (
    # (label, module, needs_database)
    ("Generate synthetic raw data", "src.generate_data", False),
    ("Clean, validate and build facts", "src.data_cleaning", False),
    ("Load PostgreSQL and create views", "src.load_to_db", True),
    ("Run SQL KPI and data-quality reports", "src.run_sql_reports", True),
    ("Compute analysis metrics", "src.analysis_metrics", False),
)


def run_stage(label: str, module: str) -> None:
    print(f"\n=== {label} ({module}) ===", flush=True)
    started = time.perf_counter()
    subprocess.run([sys.executable, "-m", module], check=True)
    print(f"--- done in {time.perf_counter() - started:.1f}s", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--skip-db", action="store_true", help="skip the PostgreSQL load and SQL report stages")
    args = parser.parse_args(argv)
    for label, module, needs_db in STAGES:
        if needs_db and args.skip_db:
            print(f"\n=== {label}: skipped (--skip-db) ===")
            continue
        try:
            run_stage(label, module)
        except subprocess.CalledProcessError as exc:
            print(f"\nPipeline stopped: {module} exited with code {exc.returncode}", file=sys.stderr)
            return exc.returncode
    print("\nPipeline complete. Launch the dashboard with: python -m streamlit run app/streamlit_app.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
