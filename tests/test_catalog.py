import importlib.util
import unittest


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("catalog"), "The snapshot catalog is required.")
        from catalog import Catalog
        self.catalog = Catalog.load()

    def test_exact_pin_conflict_requires_two_different_sodium_versions(self):
        result = self.catalog.check_pack(["bAo1Qhte", "Z8VpxxGh"])
        self.assertEqual(result["status"], "conflict")
        conflict = result["conflicts"][0]
        self.assertEqual(set(conflict["required_versions"]), {"RncWhTxD", "SMxNOGZ6"})
        self.assertEqual(set(conflict["sources"]), {"V-bAo1Qhte", "V-Z8VpxxGh"})

    def test_paired_versions_satisfy_recorded_constraints(self):
        result = self.catalog.check_pack(["bAo1Qhte", "SMxNOGZ6"])
        self.assertEqual(result["status"], "satisfies_recorded_constraints")
        self.assertIn("V-SMxNOGZ6", result["sources"])

    def test_external_dependency_is_reported_without_guessing_a_version(self):
        result = self.catalog.check_pack(["kSPJ4hQv"])
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["external_requirements"][0]["name"], "Fabric API")

    def test_catalog_refuses_unknown_versions_and_duplicate_mods(self):
        with self.assertRaisesRegex(ValueError, "outside"):
            self.catalog.check_pack(["out-of-scope"])
        with self.assertRaisesRegex(ValueError, "one version"):
            self.catalog.check_pack(["RncWhTxD", "SMxNOGZ6"])

    def test_alternatives_retain_the_requested_iris_version(self):
        result = self.catalog.alternatives(["bAo1Qhte", "Z8VpxxGh"], keep=["iris"])
        options = [option["selected"] for option in result["options"]]
        self.assertIn({"iris": "bAo1Qhte", "sodium": "SMxNOGZ6"}, options)
        self.assertTrue(all(option["iris"] == "bAo1Qhte" for option in options))
