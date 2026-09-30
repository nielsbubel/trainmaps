"""Create ignored development credentials, without printing tokens."""
import json
import secrets
from pathlib import Path

root = Path(__file__).resolve().parents[1]
folder = root / ".local"
folder.mkdir(exist_ok=True)
path = folder / "access.local.json"
if path.exists():
    config = json.loads(path.read_text(encoding="utf-8-sig"))
    if "mapping_token" not in config:
        config["mapping_token"] = secrets.token_urlsafe(32)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
        print("Mapping access added; existing tokens retained: .local/access.local.json")
    else:
        print("Existing development access retained: .local/access.local.json")
else:
    config = {"source_id": "trainmaps-development",
              "write_token": secrets.token_urlsafe(32),
              "read_token": secrets.token_urlsafe(32),
              "mapping_token": secrets.token_urlsafe(32)}
    with path.open("x", encoding="utf-8") as stream:
        json.dump(config, stream, indent=2)
        stream.write("\n")
    print("Development access created: .local/access.local.json")
