import json
import mimetypes
import os
import re
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config


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


def build_object_key(item: dict[str, Any]) -> str:
    prefix = env("R2_KEY_PREFIX", "telegram-pdfs/").strip("/")
    file_name = safe_filename(item.get("file_name") or Path(item["path"]).name)
    parts = [
        prefix,
        safe_key_part(item.get("chat_id", "chat")),
        safe_key_part(item.get("source_message_id", "source")),
        f"{safe_key_part(item.get('pdf_message_id', 'pdf'))}-{file_name}",
    ]
    return "/".join(part for part in parts if part)


def r2_client() -> Any:
    required = ["R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET"]
    missing = [name for name in required if not env(name)]
    if missing:
        raise RuntimeError(f"missing required R2 environment variable(s): {', '.join(missing)}")
    endpoint = f"https://{env('R2_ACCOUNT_ID')}.r2.cloudflarestorage.com"
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=env("R2_ACCESS_KEY_ID"),
        aws_secret_access_key=env("R2_SECRET_ACCESS_KEY"),
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )


def upload_and_sign(client: Any, item: dict[str, Any], expires_seconds: int) -> dict[str, Any]:
    path = REPO_ROOT / item["path"]
    if not path.exists():
        raise RuntimeError(f"downloaded file is missing: {path}")
    bucket = env("R2_BUCKET")
    key = build_object_key(item)
    content_type = mimetypes.guess_type(path.name)[0] or "application/pdf"
    client.upload_file(
        str(path),
        bucket,
        key,
        ExtraArgs={
            "ContentType": content_type,
            "Metadata": {
                "telegram-chat-id": str(item.get("chat_id", "")),
                "telegram-source-message-id": str(item.get("source_message_id", "")),
                "telegram-pdf-message-id": str(item.get("pdf_message_id", "")),
            },
        },
    )
    url = client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=expires_seconds,
    )
    return {
        "key": item["key"],
        "object_key": key,
        "url": url,
        "file_name": item.get("file_name") or path.name,
        "file_size": path.stat().st_size,
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


def build_body(uploaded: list[dict[str, Any]], expires_at: datetime) -> str:
    lines = [
        f"{len(uploaded)} Telegram PDF file(s) were uploaded to Cloudflare R2.",
        f"Download links expire at: {expires_at.isoformat()}",
        "",
    ]
    for index, item in enumerate(uploaded, start=1):
        match = item.get("matches", [{}])[0] if item.get("matches") else {}
        lines.extend(
            [
                f"{index}. {item['file_name']}",
                f"Size: {format_size(int(item['file_size']))}",
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
        print("no pending PDF files to upload")
        return

    expires_seconds = max(1, min(env_int("R2_URL_EXPIRES_SECONDS", 604800), 604800))
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_seconds)
    client = r2_client()
    uploaded = [upload_and_sign(client, item, expires_seconds) for item in items]
    subject_prefix = env("MAIL_SUBJECT_PREFIX", "Telegram PDF")
    subject = f"{subject_prefix}: {len(uploaded)} new file(s)"
    body = build_body(uploaded, expires_at)
    send_email(subject, body)
    write_sent_keys([item["key"] for item in uploaded])
    print(f"uploaded {len(uploaded)} PDF file(s) and sent one notification email")


if __name__ == "__main__":
    main()
