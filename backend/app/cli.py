"""Command-line tasks.

uv run python -m app.cli validate-dataset   # validate the synthetic dataset files
uv run python -m app.cli seed               # validate + load into PostgreSQL (idempotent)
uv run python -m app.cli export-schemas     # write JSON Schemas to data/schemas/
uv run python -m app.cli verify-audit       # recompute the audit hash chain
uv run python -m app.cli seed-users         # demo accounts; password from DEMO_PASSWORD (.env)
uv run python -m app.cli create-user NAME --name "..." --roles operator
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
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
from app.services.auth import upsert_user
from app.services.dataset import seed_dataset
from app.services.recovery import seed_inventory
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
            inventory = await seed_inventory(session, settings.dataset_dir / "inventory.json")
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
    print(f"inventory: version {inventory.version}")
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


def _benchmark(out: Path) -> int:
    from app.recovery.benchmark import brute_force
    from app.recovery.model import Inventory, Policy
    from app.simulation.model import Scenario

    settings = get_settings()
    files, _ = load_dataset_dir(settings.dataset_dir)
    snapshot = to_snapshot(files)
    raw = json.loads((settings.dataset_dir / "inventory.json").read_text(encoding="utf-8"))
    inventory = Inventory(version=1, renewables=raw["renewables"], consumables=raw["consumables"])
    lines = [
        "# Recovery scheduler benchmark",
        "",
        "Generated by `python -m app.cli benchmark-recovery`. Heuristic = bundle-valuation SGS",
        "(repairs only); optimum = best of all orderings under the same serial placement rules.",
        "Loss = the policy's own weighted unserved service-hours.",
        "",
        "| Scenario | Policy | Repairs | Orderings | Feasible | Heuristic loss | Optimal loss "
        "| Gap |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for path in sorted(settings.scenarios_dir.glob("*.json")):
        sc = Scenario.model_validate_json(path.read_text(encoding="utf-8"))
        for policy in Policy:
            r = brute_force(snapshot, sc.initiating_events, inventory, policy)
            lines.append(
                f"| {sc.key} | {r.policy} | {r.actions} | {r.orderings_evaluated} | "
                f"{r.feasible_orderings} | {r.heuristic_loss:,.2f} | {r.optimal_loss:,.2f} | "
                f"{r.gap_percent:.2f}% |"
            )
            print(lines[-1])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    return 0


DEMO_USERS = [
    ("viewer", "Demo Viewer", ["viewer"]),
    ("operator", "Demo Operator", ["operator"]),
    ("approver", "Demo Approver (incident commander)", ["approver"]),
    ("admin", "Demo Administrator", ["admin"]),
]


async def _upsert_users(users: list[tuple[str, str, list[str]]], password: str) -> int:
    db = Database(get_settings().database_url, pool_size=1)
    try:
        async with db.sessionmaker() as session:
            for username, display, roles in users:
                await upsert_user(
                    session, username=username, display_name=display, password=password,
                    roles=roles, actor_id="cli:users",
                )  # fmt: skip
                print(f"  {username:<10} roles={','.join(roles)}")
    except AppError as exc:
        print(f"error: {exc.detail}", file=sys.stderr)
        return 1
    finally:
        await db.dispose()
    return 0


def _seed_users() -> int:
    secret = get_settings().demo_password
    if secret is None or not secret.get_secret_value():
        print(
            "error: set DEMO_PASSWORD in your .env (at least 12 characters) to create the demo "
            "accounts. It is never committed; .env is git-ignored.",
            file=sys.stderr,
        )
        return 1
    print("Demo accounts (password from DEMO_PASSWORD):")
    return asyncio.run(_upsert_users(DEMO_USERS, secret.get_secret_value()))


def _create_user(username: str, display: str, roles: list[str]) -> int:
    password = os.environ.get("AFTERMATH_NEW_PASSWORD") or getpass.getpass(
        f"Password for {username}: "
    )
    return asyncio.run(_upsert_users([(username, display, roles)], password))


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
    p = sub.add_parser("benchmark-recovery")
    p.add_argument(
        "--out",
        type=Path,
        default=settings.data_dir.parent / "docs" / "reports" / "RECOVERY_BENCHMARK.md",
    )
    p = sub.add_parser("export-openapi")
    p.add_argument(
        "--out", type=Path, default=settings.data_dir.parent / "frontend" / "types" / "openapi.json"
    )
    sub.add_parser("seed-users", help="create/reset the four demo accounts from DEMO_PASSWORD")
    p = sub.add_parser("create-user", help="create or reset one user (password prompted)")
    p.add_argument("username")
    p.add_argument("--name", required=True, help="display name")
    p.add_argument("--roles", required=True, help="comma-separated: viewer,operator,approver,admin")
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
        case "benchmark-recovery":
            return _benchmark(args.out)
        case "export-openapi":
            return _export_openapi(args.out)
        case "seed-users":
            return _seed_users()
        case "create-user":
            return _create_user(args.username, args.name, args.roles.split(","))
    return 2


if __name__ == "__main__":
    sys.exit(main())
