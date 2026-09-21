from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from standardsforge.pack import validate_pack_directory  # noqa: E402
from standardsforge.policy import load_policy  # noqa: E402
from standardsforge.source_catalog import load_source_catalog  # noqa: E402


def load_json(relative: str):
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def main() -> int:
    contract_files = sorted((ROOT / "contracts").glob("*.json"))
    for contract_file in contract_files:
        json.loads(contract_file.read_text(encoding="utf-8"))
    requirements = load_json("docs/requirements/requirements.json")
    tasks = load_json("backlog/tasks.json")
    requirement_ids = {item["id"] for item in requirements["requirements"]}
    for task in tasks["tasks"]:
        missing = sorted(set(task["requirements"]) - requirement_ids)
        if missing:
            raise SystemExit(f"{task['task_id']} references missing requirements: {missing}")

    packs = []
    for relative in (
        "examples/packs/fictional-adapter-v1",
        "examples/packs/fictional-adapter-v2",
    ):
        pack = validate_pack_directory(ROOT / relative)
        packs.append(
            {
                "pack_id": pack.manifest["pack_id"],
                "edition_id": pack.manifest["edition_id"],
                "package_digest": pack.package_digest,
                "records": len(pack.records),
            }
        )

    policy = load_policy(ROOT / "examples/policies/local-synthetic.json")
    source_catalogs = [
        load_source_catalog(ROOT / "catalog/mil-format-authorities.json"),
        load_source_catalog(ROOT / "catalog/mil-std-810h.json"),
    ]
    output = {
        "ok": True,
        "task_ids": [task["task_id"] for task in tasks["tasks"]],
        "requirement_count": len(requirement_ids),
        "contract_documents": [path.name for path in contract_files],
        "packs": packs,
        "policy_fingerprint": policy.fingerprint,
        "source_catalogs": [
            {
                "catalog_id": source_catalog["catalog_id"],
                "documents": [document["document_id"] for document in source_catalog["documents"]],
            }
            for source_catalog in source_catalogs
        ],
        "limitations": [
            "Real source PDFs are local ignored inputs, not repository fixtures.",
            "PDF text-layer compilation, one full-document unreviewed derived outline, and one reviewed structural slice are implemented; document-wide visual and reviewed semantic extraction remain unqualified."
        ],
    }
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
