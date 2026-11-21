"""Command-line tasks.

uv run python -m app.cli validate-dataset   # validate the synthetic dataset files
uv run python -m app.cli seed               # validate + load into PostgreSQL (idempotent)
uv run python -m app.cli export-schemas     # write JSON Schemas to data/schemas/
uv run python -m app.cli verify-audit       # recompute the audit hash chain
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from app.core.config import get_settings
from app.core.errors import AppError
from app.database.session import Database
from app.graph.dataset import (
    DatasetFiles,
    DatasetManifest,
    DependentRecord,
    load_dataset_dir,
    to_snapshot,
)
from app.graph.model import Asset
from app.graph.validation import Severity, validate_snapshot
from app.services.audit import verify_chain
from app.services.dataset import seed_dataset
from app.services.scenarios import load_scenario_files, sync_scenarios


def _validate(directory: Path) -> int:
    files, _ = load_dataset_dir(directory)
    snapshot = to_snapshot(files)
    issues = validate_snapshot(snapshot)
    for issue in issues:
        print(f"{issue.severity:7} {issue.rule} {issue.subject}: {issue.message}")
    errors = sum(1 for i in issues if i.severity is Severity.ERROR)
    print(
        f"{snapshot.dataset_name}@{snapshot.dataset_version}: {len(snapshot.assets)} assets, "
        f"{len(snapshot.dependencies)} dependencies, {errors} error(s), "
        f"{len(issues) - errors} warning(s); hash {snapshot.content_hash[:16]}"
    )
    return 1 if errors else 0


async def _seed(directory: Path) -> int:
    settings = get_settings()
    files, basemap = load_dataset_dir(directory)
    db = Database(settings.database_url, pool_size=1)
    try:
        async with db.sessionmaker() as session, session.begin():
            result = await seed_dataset(session, files, basemap, actor_id="cli:seed")
            synced = await sync_scenarios(
                session,
                to_snapshot(files),
                load_scenario_files(settings.scenarios_dir),
                actor_id="cli:seed",
            )
    except AppError as exc:
        print(f"seed failed: {exc.detail}", file=sys.stderr)
        for issue in exc.extra.get("issues", []):
            print(f"  {issue}", file=sys.stderr)
        return 1
    finally:
        await db.dispose()
    print(
        f"{result.status}: {result.name}@{result.version} "
        f"({result.asset_count} assets, {result.dependency_count} dependencies, "
        f"hash {result.content_hash[:16]})"
    )
    print(
        f"scenarios: created={synced.created} updated={synced.updated} "
        f"unchanged={len(synced.unchanged)}"
    )
    return 0


async def _verify_audit() -> int:
    db = Database(get_settings().database_url, pool_size=1)
    try:
        async with db.sessionmaker() as session:
            result = await verify_chain(session)
    finally:
        await db.dispose()
    print(
        f"audit chain ok={result.ok} checked={result.records_checked} "
        f"first_broken_id={result.first_broken_id}"
    )
    return 0 if result.ok else 1


def _export_schemas(out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    schemas = {
        "manifest.schema.json": DatasetManifest.model_json_schema(),
        "assets.schema.json": {"type": "array", "items": Asset.model_json_schema()},
        "dependencies.schema.json": {
            "type": "array",
            "items": DependentRecord.model_json_schema(),
        },
        "dataset.schema.json": DatasetFiles.model_json_schema(),
    }
    for name, schema in schemas.items():
        schema = {"$schema": "https://json-schema.org/draft/2020-12/schema", **schema}
        (out / name).write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {out / name}")
    return 0


def _export_openapi(out: Path) -> int:
    from app.main import create_app

    spec = create_app().openapi()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(prog="aftermath")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("validate-dataset", "seed"):
        p = sub.add_parser(name)
        p.add_argument("--dataset-dir", type=Path, default=settings.dataset_dir)
    p = sub.add_parser("export-schemas")
    p.add_argument("--out", type=Path, default=settings.data_dir / "schemas")
    sub.add_parser("verify-audit")
    p = sub.add_parser("export-openapi")
    p.add_argument(
        "--out", type=Path, default=settings.data_dir.parent / "frontend" / "types" / "openapi.json"
    )
    args = parser.parse_args(argv)

    match args.command:
        case "validate-dataset":
            return _validate(args.dataset_dir)
        case "seed":
            return asyncio.run(_seed(args.dataset_dir))
        case "export-schemas":
            return _export_schemas(args.out)
        case "verify-audit":
            return asyncio.run(_verify_audit())
        case "export-openapi":
            return _export_openapi(args.out)
    return 2


if __name__ == "__main__":
    sys.exit(main())
