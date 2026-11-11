"""Read-only version catalog and deterministic checks for declared constraints."""

import itertools
import json
import re
from collections import defaultdict
from pathlib import Path

SNAPSHOT = Path(__file__).parent / "data" / "catalog.json"
EXTERNAL_NAMES = {"P7dR8mSH": "Fabric API"}


class Catalog:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.projects = snapshot["projects"]
        self.project_slugs = {entry["id"]: slug for slug, entry in self.projects.items()}
        self.versions = {}
        self.evidence = {note["id"]: note for note in snapshot["notes"]}
        for slug, project in self.projects.items():
            for record in project["versions"]:
                version_id = record["id"]
                url = f"https://modrinth.com/mod/{slug}/version/{version_id}"
                version = dict(record, mod=slug, name=project["name"], source=f"V-{version_id}", url=url)
                self.versions[version_id] = version
                self.evidence[version["source"]] = {
                    "id": version["source"],
                    "title": f'{version["name"]} {version["version_number"]}',
                    "url": url,
                }
            self.evidence[f"P-{slug}"] = {
                "id": f"P-{slug}",
                "title": f'{project["name"]} · Modrinth version query',
                "url": project["api_url"],
            }

    @classmethod
    def load(cls, path=SNAPSHOT):
        with Path(path).open(encoding="utf-8") as handle:
            return cls(json.load(handle))

    def summary(self):
        return {
            "minecraft": self.snapshot["minecraft"],
            "loader": self.snapshot["loader"],
            "retrieved_at": self.snapshot["retrieved_at"],
            "mods": [
                {"slug": slug, "name": p["name"], "count": len(p["versions"])}
                for slug, p in self.projects.items()
            ],
        }

    def list_versions(self, mod):
        slug = mod.strip().lower()
        if slug not in self.projects:
            raise ValueError(f"'{mod}' is outside the four-mod catalog.")
        return {
            "versions": [
                {key: v[key] for key in ("id", "version_number", "version_type", "source")}
                for v in self.versions.values() if v["mod"] == slug
            ],
            "sources": [f"P-{slug}"],
        }

    def version(self, version_id):
        if version_id not in self.versions:
            raise ValueError(f"'{version_id}' is outside the Minecraft 1.21.1 Fabric snapshot.")
        return self.versions[version_id]

    def notes(self, mod):
        slug = mod.strip().lower()
        if slug not in self.projects:
            raise ValueError(f"'{mod}' is outside the four-mod catalog.")
        notes = [note for note in self.snapshot["notes"] if note["mod"] == slug]
        return {"notes": notes, "sources": [note["id"] for note in notes]}

    def selected(self, version_ids):
        if not version_ids:
            raise ValueError("Select at least one version.")
        pack = {}
        for vid in version_ids:
            v = self.version(vid)
            if v["mod"] in pack:
                raise ValueError(f"Select only one version of {v['name']}.")
            pack[v["mod"]] = v
        return pack

    def target_mod(self, dep):
        if dep["version_id"] in self.versions:
            return self.versions[dep["version_id"]]["mod"]
        return self.project_slugs.get(dep["project_id"])

    def check_pack(self, version_ids):
        selected = self.selected(version_ids)
        requirements = []
        external = []
        conflicts = []
        missing = []
        pins = defaultdict(list)
        for mod, v in selected.items():
            for dep in v["dependencies"]:
                kind = dep["dependency_type"]
                if kind not in ("required", "incompatible"):
                    continue
                target = self.target_mod(dep)
                pin = dep["version_id"]
                edge = {
                    "from": mod, "target": target, "version_id": pin,
                    "kind": kind, "source": v["source"],
                }
                if target is None:
                    name = EXTERNAL_NAMES.get(dep["project_id"]) or dep["file_name"] or dep["project_id"] or pin
                    external.append(dict(edge, name=name))
                    continue
                requirements.append(edge)
                if kind == "required":
                    if pin:
                        pins[target].append(edge)
                    if target not in selected:
                        missing.append(dict(edge, available_in_snapshot=pin is None or pin in self.versions))
                elif target in selected and (pin is None or pin == selected[target]["id"]):
                    conflicts.append({
                        "kind": "declared_incompatible", "mod": target,
                        "sources": [v["source"], selected[target]["source"]],
                    })

        for target, edges in pins.items():
            required = sorted({edge["version_id"] for edge in edges})
            actual = selected[target]["id"] if target in selected else None
            sources = [edge["source"] for edge in edges]
            if len(required) > 1:
                conflicts.append({
                    "kind": "contradictory_pins", "mod": target,
                    "required_versions": required, "sources": sources,
                })
            elif actual and actual != required[0]:
                conflicts.append({
                    "kind": "pin_mismatch", "mod": target,
                    "required_versions": required, "selected_version": actual,
                    "sources": [*sources, selected[target]["source"]],
                })

        if "sodium" in selected and "indium" in selected:
            sodium = selected["sodium"]
            version = re.search(r"(?<![0-9.])0\.(\d+)\.\d+", sodium["version_number"])
            if version and int(version.group(1)) >= 6:
                conflicts.append({
                    "kind": "maintainer_incompatibility", "mod": "indium",
                    "sources": ["N-INDIUM", sodium["source"], selected["indium"]["source"]],
                })

        source_ids = {v["source"] for v in selected.values()}
        for entry in conflicts:
            source_ids.update(entry["sources"])
        for edge in requirements:
            if edge["version_id"] in self.versions:
                source_ids.add(self.versions[edge["version_id"]]["source"])
        return {
            "status": "conflict" if conflicts else "incomplete" if missing or external
                      else "satisfies_recorded_constraints",
            "selected": {slug: v["id"] for slug, v in selected.items()},
            "requirements": requirements,
            "conflicts": conflicts,
            "missing": missing,
            "external_requirements": external,
            "sources": sorted(source_ids),
            "limit": "This checks recorded metadata and selected maintainer notes. No launch or gameplay test was performed.",
        }

    def alternatives(self, version_ids, keep):
        original = self.selected(version_ids)
        if any(slug not in original for slug in keep):
            raise ValueError("A locked mod must be present in the original pack.")
        scope = set(original)
        while True:
            dependencies = {
                self.target_mod(dep)
                for v in self.versions.values() if v["mod"] in scope
                for dep in v["dependencies"] if dep["dependency_type"] == "required"
            } - {None}
            if dependencies <= scope:
                break
            scope.update(dependencies)
        mods = sorted(scope)
        domains = [
            [original[mod]["id"]] if mod in keep else
            [None, *(v["id"] for v in self.versions.values() if v["mod"] == mod)]
            for mod in mods
        ]
        candidates = []
        for combination in itertools.product(*domains):
            chosen = dict(zip(mods, combination))
            ids = [vid for vid in combination if vid]
            if not ids or not any(chosen[mod] for mod in original):
                continue
            result = self.check_pack(ids)
            if result["conflicts"] or result["missing"]:
                continue
            used = {edge["target"] for edge in result["requirements"] if edge["kind"] == "required"}
            if any(vid and mod not in original and mod not in used for mod, vid in chosen.items()):
                continue
            changes = [
                {"mod": mod, "from": original.get(mod, {}).get("id"), "to": vid}
                for mod, vid in chosen.items() if original.get(mod, {}).get("id") != vid
            ]
            if not changes:
                continue
            candidates.append({
                "selected": result["selected"], "changes": changes,
                "status": result["status"], "external_requirements": result["external_requirements"],
                "sources": result["sources"],
            })
        candidates.sort(key=lambda c: (
            len(c["changes"]), sum(change["to"] is None for change in c["changes"]),
            len(c["external_requirements"]),
            sum("beta" in self.versions[vid]["version_number"].lower() for vid in c["selected"].values()),
            tuple(c["selected"].values()),
        ))
        options = candidates[:3]
        return {
            "options": options,
            "sources": sorted({source for option in options for source in option["sources"]}),
            "limit": "Alternatives satisfy the recorded constraints within this snapshot, subject to any listed external requirements.",
        }
