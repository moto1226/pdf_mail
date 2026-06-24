import json
import os
import shutil
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def env_int(name: str, default: int) -> int:
    value = env(name)
    if not value:
        return default
    return int(value)


def load_manifest(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_sent_keys(keys: list[str]) -> None:
    path = REPO_ROOT / env("SENT_KEYS_FILE", "run/sent-keys.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"sent_keys": keys}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def safe_subject(value: str) -> str:
    return " ".join(value.replace("\r", " ").replace("\n", " ").split())[:180]


def maybe_zip(path: Path, threshold_mb: int, target_dir: Path) -> Path:
    if threshold_mb <= 0 or path.stat().st_size <= threshold_mb * 1024 * 1024:
        return path
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{path.stem}.zip"
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(path, arcname=path.name)
    return target


def write_body(item: dict[str, Any], attachment: Path, body_dir: Path) -> Path:
    body_dir.mkdir(parents=True, exist_ok=True)
    matches = item.get("matches", [])
    first_match = matches[0] if matches else {}
    lines = [
        "Telegram PDF matched and downloaded.",
        "",
        f"File: {item.get('file_name', attachment.name)}",
        f"Attachment: {attachment.name}",
        f"Chat: {item.get('chat_id', '')}",
        f"Source message id: {item.get('source_message_id', '')}",
        f"PDF message id: {item.get('pdf_message_id', '')}",
        f"Matched in: {first_match.get('location', '')}",
        f"Matched message id: {first_match.get('message_id', '')}",
        f"Matched text: {first_match.get('matched_text', '')}",
        f"Snippet: {first_match.get('snippet', '')}",
        f"Sent at: {datetime.now(timezone.utc).isoformat()}",
    ]
    path = body_dir / f"{item['pdf_message_id']}.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def run_mail_action(item: dict[str, Any], attachment: Path, body_file: Path) -> None:
    action_dir = REPO_ROOT / env("MAIL_ACTION_DIR", ".actions/action-send-mail")
    node = shutil.which("node")
    if not node:
        raise RuntimeError("node was not found")
    main_js = action_dir / "main.js"
    if not main_js.exists():
        raise RuntimeError(f"action-send-mail main.js not found at {main_js}")

    subject_prefix = env("MAIL_SUBJECT_PREFIX", "Telegram PDF")
    subject = safe_subject(f"{subject_prefix}: {item.get('file_name', attachment.name)}")
    action_env = os.environ.copy()
    action_env.update(
        {
            "INPUT_SERVER_ADDRESS": env("SMTP_SERVER"),
            "INPUT_SERVER_PORT": env("SMTP_PORT", "465"),
            "INPUT_SECURE": env("SMTP_SECURE", "true"),
            "INPUT_USERNAME": env("SMTP_USERNAME"),
            "INPUT_PASSWORD": env("SMTP_PASSWORD"),
            "INPUT_FROM": env("MAIL_FROM"),
            "INPUT_TO": env("MAIL_TO"),
            "INPUT_CC": env("MAIL_CC"),
            "INPUT_BCC": env("MAIL_BCC"),
            "INPUT_SUBJECT": subject,
            "INPUT_BODY": f"file://{body_file}",
            "INPUT_ATTACHMENTS": str(attachment),
        }
    )
    required = ["SMTP_SERVER", "SMTP_USERNAME", "SMTP_PASSWORD", "MAIL_FROM", "MAIL_TO"]
    missing = [name for name in required if not env(name)]
    if missing:
        raise RuntimeError(f"missing required mail environment variable(s): {', '.join(missing)}")
    subprocess.run([node, str(main_js)], cwd=str(action_dir), env=action_env, check=True)


def main() -> None:
    manifest_path = REPO_ROOT / env("MANIFEST_FILE", "run/pending-mails.json")
    manifest = load_manifest(manifest_path)
    items = manifest.get("items", [])
    if not items:
        print("no pending PDF files to mail")
        return

    zip_threshold_mb = env_int("ZIP_THRESHOLD_MB", 45)
    max_attachment_mb = env_int("SMTP_MAX_ATTACHMENT_MB", 0)
    attachment_dir = REPO_ROOT / "run" / "mail-attachments"
    body_dir = REPO_ROOT / "run" / "mail-bodies"
    sent_keys: list[str] = []
    failures: list[str] = []
    write_sent_keys(sent_keys)

    for item in items:
        try:
            original = REPO_ROOT / item["path"]
            attachment = maybe_zip(original, zip_threshold_mb, attachment_dir)
            if max_attachment_mb > 0 and attachment.stat().st_size > max_attachment_mb * 1024 * 1024:
                raise RuntimeError(f"{attachment.name} exceeds SMTP_MAX_ATTACHMENT_MB after zip")
            body_file = write_body(item, attachment, body_dir)
            print(f"sending {attachment.name}")
            run_mail_action(item, attachment, body_file)
            sent_keys.append(item["key"])
            write_sent_keys(sent_keys)
        except Exception as exc:
            failures.append(f"{item.get('file_name', item.get('key', 'unknown'))}: {exc}")

    if failures:
        raise RuntimeError("one or more emails failed: " + "; ".join(failures))


if __name__ == "__main__":
    main()

