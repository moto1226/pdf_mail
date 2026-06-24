import json
import os
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def main() -> None:
    state_file = REPO_ROOT / env("STATE_FILE", "state/pdf-mail-state.json")
    next_state_file = REPO_ROOT / env("NEXT_STATE_FILE", "run/next-state.json")
    manifest_file = REPO_ROOT / env("MANIFEST_FILE", "run/pending-mails.json")
    sent_keys_file = REPO_ROOT / env("SENT_KEYS_FILE", "run/sent-keys.json")
    final_state_file = REPO_ROOT / env("FINAL_STATE_FILE", "run/final-state.json")
    max_processed = int(env("MAX_PROCESSED_KEYS", "5000"))

    current_state = load_json(state_file, {"version": 1, "chats": {}})
    next_state = load_json(next_state_file, current_state)
    manifest = load_json(manifest_file, {"items": []})
    items = manifest.get("items", [])

    if not items:
        write_json(final_state_file, next_state)
        print("finalized state with no pending emails")
        return

    sent_keys = set(load_json(sent_keys_file, {"sent_keys": []}).get("sent_keys", []))
    item_keys = {item["key"] for item in items}
    if item_keys and item_keys.issubset(sent_keys):
        write_json(final_state_file, next_state)
        print("finalized state after all emails succeeded")
        return

    final_state = current_state
    for item in items:
        if item["key"] not in sent_keys:
            continue
        chat_id = str(item["chat_id"])
        chat_state = final_state.setdefault("chats", {}).setdefault(chat_id, {})
        processed = list(dict.fromkeys(chat_state.get("processed", [])))
        processed.append(item["key"])
        chat_state["processed"] = list(dict.fromkeys(processed))[-max_processed:]

    write_json(final_state_file, final_state)
    print(f"finalized partial state for {len(sent_keys)} sent email(s)")


if __name__ == "__main__":
    main()

