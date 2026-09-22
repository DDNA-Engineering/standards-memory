from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from jsonschema import SchemaError, ValidationError
from jsonschema.validators import validator_for


ROOT = Path(__file__).resolve().parents[1]

import sys

sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import validate_contracts as contracts_gate  # noqa: E402
from standardsforge.service import StandardsForgeService  # noqa: E402


class ContractValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.schemas = contracts_gate.load_schemas()
        self.registry = contracts_gate.check_schema_documents(self.schemas)
        self.temporary = tempfile.TemporaryDirectory(
            prefix="standardsforge-contract-test-"
        )
        base = Path(self.temporary.name)
        self.service = StandardsForgeService(base / "memory.db", base / "objects")
        policy = ROOT / "examples" / "policies" / "local-synthetic.json"
        self.first_digest = self.service.install_pack(
            ROOT / "examples" / "packs" / "fictional-adapter-v1", policy
        )["package_digest"]
        self.second_digest = self.service.install_pack(
            ROOT / "examples" / "packs" / "fictional-adapter-v2", policy
        )["package_digest"]

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _validate(self, schema_name: str, instance: object) -> None:
        contracts_gate.validate_with_schema(
            self.schemas, self.registry, schema_name, instance
        )

    def test_actual_results_profiles_continuations_and_errors_validate(self) -> None:
        counts = contracts_gate.validate_actual_query_contracts(
            self.schemas, self.registry
        )
        self.assertEqual(
            {
                "detailed_results": 12,
                "profile_results": 4,
                "doctor_results": 1,
                "handoff_results": 1,
                "typed_errors": 4,
                "negative_cases": 12,
            },
            counts,
        )

    def test_malformed_schema_and_response_shapes_fail(self) -> None:
        malformed_schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "not-a-json-schema-type",
        }
        with self.assertRaises(SchemaError):
            validator_for(malformed_schema).check_schema(malformed_schema)

        search = self.service.search("axial load", "local-user")
        resolve = self.service.resolve_document(
            "EXAMPLE-SPEC-100",
            "local-user",
            "example:spec-100:2025-a",
            "curated_records",
        )
        first_page = self.service.enumerate_obligations(
            self.first_digest, "local-user", limit=1
        )
        document_page = self.service.list_documents("local-user", limit=1)

        mutations = []
        missing_operation = copy.deepcopy(search)
        del missing_operation["operation"]
        mutations.append(missing_operation)

        extra_field = copy.deepcopy(search)
        extra_field["undeclared"] = True
        mutations.append(extra_field)

        invalid_digest = copy.deepcopy(resolve)
        invalid_digest["package_digest"] = "not-a-digest"
        mutations.append(invalid_digest)

        wrong_scalar = copy.deepcopy(first_page)
        wrong_scalar["page"]["returned"] = "one"
        mutations.append(wrong_scalar)

        inconsistent_cursor = copy.deepcopy(first_page)
        inconsistent_cursor["page"]["next_cursor"] = None
        mutations.append(inconsistent_cursor)

        extra_document_field = copy.deepcopy(document_page)
        extra_document_field["documents"][0]["undeclared"] = True
        mutations.append(extra_document_field)

        inconsistent_document_cursor = copy.deepcopy(document_page)
        inconsistent_document_cursor["page"]["next_cursor"] = None
        mutations.append(inconsistent_document_cursor)

        for mutation in mutations:
            with self.subTest(operation=mutation.get("operation")):
                with self.assertRaises(ValidationError):
                    self._validate("query-response.schema.json", mutation)

        with self.assertRaises(ValidationError):
            self._validate(
                "error-response.schema.json",
                {"ok": False, "error": {"code": "invalid_query"}},
            )


if __name__ == "__main__":
    unittest.main()
