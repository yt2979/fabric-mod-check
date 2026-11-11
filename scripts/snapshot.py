"""Capture public version records for the four curated projects."""
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

PROJECTS = {
    "sodium": ("Sodium", "AANobbMI"),
    "iris": ("Iris", "YL57xq9U"),
    "indium": ("Indium", "Orvt0mRa"),
    "continuity": ("Continuity", "1IjD5062"),
}
NOTES = [
    {
        "id": "N-INDIUM",
        "mod": "indium",
        "title": "Indium maintainer compatibility notice",
        "url": "https://modrinth.com/project/indium",
        "text": "The maintainer says Sodium 0.6 and later include Fabric Rendering API support. Indium is unnecessary for that purpose and is incompatible with Sodium 0.6 and later.",
    },
    {
        "id": "N-SODIUM",
        "mod": "sodium",
        "title": "Sodium 0.6 Fabric Rendering API announcement",
        "url": "https://modrinth.com/mod/sodium/version/oZOSEhyy",
        "text": "The Sodium 0.6 release notes describe Fabric Rendering API support built into Sodium, replacing the need for Indium to provide that support.",
    },
]

def main():
    params = urlencode({"loaders": '["fabric"]', "game_versions": '["1.21.1"]'})
    keys = ("id", "project_id", "version_number", "version_type", "date_published",
            "game_versions", "loaders", "dependencies")
    snapshot = {
        "minecraft": "1.21.1", "loader": "fabric",
        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "projects": {}, "notes": NOTES,
    }
    for slug, (name, expected_id) in PROJECTS.items():
        url = f"https://api.modrinth.com/v2/project/{slug}/version?{params}"
        request = Request(url, headers={"User-Agent": "columbia-course-project/fabric-mod-check/1.0"})
        with urlopen(request, timeout=20) as response:
            rows = json.load(response)
        ids = {row["project_id"] for row in rows}
        if ids != {expected_id}:
            raise ValueError(f"Unexpected project IDs for {slug}: {ids}")
        rows = [row for row in rows if "fabric" in row["loaders"] and "1.21.1" in row["game_versions"]]
        if not rows or len({row["id"] for row in rows}) != len(rows):
            raise ValueError(f"Missing or duplicate version records for {slug}")
        snapshot["projects"][slug] = {
            "name": name, "id": expected_id, "api_url": url,
            "versions": [{key: row[key] for key in keys} for row in rows],
        }
        print(f"{slug}: {len(rows)} records")
    target = Path(__file__).resolve().parents[1] / "data" / "catalog.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(target)

if __name__ == "__main__":
    main()
