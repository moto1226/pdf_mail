import json
import os
import re
import shutil
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any
from urllib.parse import quote


REPO_ROOT = Path(__file__).resolve().parents[1]


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def env_int(name: str, default: int) -> int:
    value = env(name)
    if not value:
        return default
    return int(value)


def load_manifest(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def write_sent_keys(keys: list[str]) -> None:
    path = REPO_ROOT / env("SENT_KEYS_FILE", "run/sent-keys.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"sent_keys": keys}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def split_addresses(value: str) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in re.split(r"[,;]", value) if part.strip()]


def safe_filename(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")
    return cleaned or "document.pdf"


def safe_key_part(value: Any) -> str:
    return re.sub(r"[^A-Za-z0-9._=-]+", "_", str(value)).strip("_") or "unknown"


def repo_relative_pdf_path(item: dict[str, Any]) -> Path:
    base_dir = env("PDF_REPO_DIR", "files").strip("/\\") or "files"
    file_name = safe_filename(item.get("file_name") or Path(item["path"]).name)
    return Path(base_dir) / safe_key_part(item.get("chat_id", "chat")) / safe_key_part(
        item.get("source_message_id", "source")
    ) / f"{safe_key_part(item.get('pdf_message_id', 'pdf'))}-{file_name}"


def public_base_url() -> str:
    configured = env("PUBLIC_BASE_URL")
    if configured:
        return configured.rstrip("/")
    repository = env("GITHUB_REPOSITORY", "moto1226/pdf_mail")
    ref_name = env("GITHUB_REF_NAME", "main")
    return f"https://raw.githubusercontent.com/{repository}/{ref_name}"


def public_url(path: Path) -> str:
    normalized = path.as_posix()
    return f"{public_base_url()}/{quote(normalized, safe='/')}"


def copy_pdf_to_repo(item: dict[str, Any]) -> dict[str, Any]:
    source = REPO_ROOT / item["path"]
    if not source.exists():
        raise RuntimeError(f"downloaded file is missing: {source}")
    max_mb = env_int("MAX_REPO_FILE_MB", 95)
    if max_mb > 0 and source.stat().st_size > max_mb * 1024 * 1024:
        raise RuntimeError(f"{source.name} exceeds MAX_REPO_FILE_MB={max_mb}")

    relative_path = repo_relative_pdf_path(item)
    target = REPO_ROOT / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return {
        "key": item["key"],
        "repo_path": relative_path.as_posix(),
        "url": public_url(relative_path),
        "file_name": item.get("file_name") or source.name,
        "file_size": target.stat().st_size,
        "chat_id": item.get("chat_id", ""),
        "source_message_id": item.get("source_message_id", ""),
        "pdf_message_id": item.get("pdf_message_id", ""),
        "matches": item.get("matches", []),
    }


def format_size(size: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} {unit}"
        value /= 1024
    return f"{size} B"


def build_body(files: list[dict[str, Any]]) -> str:
    lines = [
        f"{len(files)} Telegram PDF file(s) were saved to the GitHub repository.",
        "Download links are raw GitHub file links. They work without login only when the repository is public.",
        "Links become available after this workflow commits the files.",
        f"Generated at: {datetime.now(timezone.utc).isoformat()}",
        "",
    ]
    for index, item in enumerate(files, start=1):
        match = item.get("matches", [{}])[0] if item.get("matches") else {}
        lines.extend(
            [
                f"{index}. {item['file_name']}",
                f"Size: {format_size(int(item['file_size']))}",
                f"Repository path: {item['repo_path']}",
                f"Chat: {item.get('chat_id', '')}",
                f"Source message id: {item.get('source_message_id', '')}",
                f"PDF message id: {item.get('pdf_message_id', '')}",
                f"Matched in: {match.get('location', '')}",
                f"Matched text: {match.get('matched_text', '')}",
                f"Snippet: {match.get('snippet', '')}",
                f"Download: {item['url']}",
                "",
            ]
        )
    return "\n".join(lines)


def send_email(subject: str, body: str) -> None:
    required = ["SMTP_SERVER", "SMTP_USERNAME", "SMTP_PASSWORD", "MAIL_FROM", "MAIL_TO"]
    missing = [name for name in required if not env(name)]
    if missing:
        raise RuntimeError(f"missing required mail environment variable(s): {', '.join(missing)}")

    to_addrs = split_addresses(env("MAIL_TO"))
    cc_addrs = split_addresses(env("MAIL_CC"))
    bcc_addrs = split_addresses(env("MAIL_BCC"))
    recipients = to_addrs + cc_addrs + bcc_addrs
    if not recipients:
        raise RuntimeError("no mail recipients configured")

    message = EmailMessage()
    message["From"] = env("MAIL_FROM")
    message["To"] = ", ".join(to_addrs)
    if cc_addrs:
        message["Cc"] = ", ".join(cc_addrs)
    message["Subject"] = subject
    message.set_content(body)

    server = env("SMTP_SERVER")
    port = env_int("SMTP_PORT", 465)
    secure = env("SMTP_SECURE", "true").lower() != "false"
    if secure:
        with smtplib.SMTP_SSL(server, port, timeout=60) as smtp:
            smtp.login(env("SMTP_USERNAME"), env("SMTP_PASSWORD"))
            smtp.send_message(message, to_addrs=recipients)
    else:
        with smtplib.SMTP(server, port, timeout=60) as smtp:
            if env("SMTP_STARTTLS", "false").lower() == "true":
                smtp.starttls()
            smtp.login(env("SMTP_USERNAME"), env("SMTP_PASSWORD"))
            smtp.send_message(message, to_addrs=recipients)


def main() -> None:
    manifest_path = REPO_ROOT / env("MANIFEST_FILE", "run/pending-mails.json")
    manifest = load_manifest(manifest_path)
    items = manifest.get("items", [])
    write_sent_keys([])
    if not items:
        print("no pending PDF files to save")
        return

    saved_files = [copy_pdf_to_repo(item) for item in items]
    subject_prefix = env("MAIL_SUBJECT_PREFIX", "Telegram PDF")
    subject = f"{subject_prefix}: {len(saved_files)} new file(s)"
    send_email(subject, build_body(saved_files))
    write_sent_keys([item["key"] for item in saved_files])
    print(f"saved {len(saved_files)} PDF file(s) and sent one notification email")


if __name__ == "__main__":
    main()
