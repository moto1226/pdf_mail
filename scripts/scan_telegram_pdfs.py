import asyncio
import base64
import json
import os
import re
from pathlib import Path
from typing import Any

from pyrogram import Client


REPO_ROOT = Path(__file__).resolve().parents[1]


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def env_int(name: str, default: int) -> int:
    value = env(name)
    if not value:
        return default
    return int(value)


def load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def sanitize_filename(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return cleaned or "document.pdf"


def text_for_match(message: Any) -> str:
    parts = []
    for attr in ("text", "caption"):
        value = getattr(message, attr, None)
        if value:
            parts.append(str(value))
    document = getattr(message, "document", None)
    file_name = getattr(document, "file_name", None)
    if file_name:
        parts.append(str(file_name))
    return "\n".join(parts)


def is_pdf(message: Any) -> bool:
    document = getattr(message, "document", None)
    if not document:
        return False
    file_name = (getattr(document, "file_name", "") or "").lower()
    mime_type = (getattr(document, "mime_type", "") or "").lower()
    return file_name.endswith(".pdf") or mime_type == "application/pdf"


def pdf_identity(chat_id: str, message: Any) -> str:
    document = getattr(message, "document", None)
    unique_id = getattr(document, "file_unique_id", "") or getattr(document, "file_id", "")
    return f"{chat_id}:{message.id}:{unique_id}"


def match_info(pattern: re.Pattern[str], message: Any, location: str) -> dict[str, Any] | None:
    text = text_for_match(message)
    found = pattern.search(text)
    if not found:
        return None
    snippet = " ".join(text[max(0, found.start() - 80) : found.end() + 80].split())
    return {
        "location": location,
        "message_id": message.id,
        "matched_text": found.group(0),
        "snippet": snippet,
    }


async def get_replies(client: Client, chat_id: str, message_id: int, limit: int) -> list[Any]:
    if limit <= 0 or not hasattr(client, "get_discussion_replies"):
        return []
    replies = []
    try:
        async for reply in client.get_discussion_replies(chat_id, message_id, limit=limit):
            replies.append(reply)
    except TypeError:
        count = 0
        try:
            async for reply in client.get_discussion_replies(chat_id, message_id):
                replies.append(reply)
                count += 1
                if count >= limit:
                    break
        except Exception as exc:
            print(f"warning: could not read replies for message {message_id}: {type(exc).__name__}")
    except Exception as exc:
        print(f"warning: could not read replies for message {message_id}: {type(exc).__name__}")
    return replies


async def download_pdf(client: Client, message: Any, chat_id: str, download_dir: Path) -> str:
    document = message.document
    original = sanitize_filename(getattr(document, "file_name", "") or f"{message.id}.pdf")
    if not original.lower().endswith(".pdf"):
        original = f"{original}.pdf"
    target = download_dir / sanitize_filename(f"{chat_id}_{message.id}_{original}")
    downloaded = await client.download_media(message, file_name=str(target))
    if not downloaded:
        raise RuntimeError(f"download_media returned no path for message {message.id}")
    return str(Path(downloaded).resolve())


def prepare_session_file(session_dir: Path) -> None:
    encoded = env("TELEGRAM_SESSION_FILE_B64")
    if not encoded:
        return
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "pdf_mail.session").write_bytes(base64.b64decode(encoded))


def source_with_recipients(source: dict[str, Any], recipients: dict[str, str] | None = None) -> dict[str, str]:
    recipients = recipients or {}
    return {
        "chat_id": str(source.get("chat_id", "")).strip(),
        "match_regex": str(source.get("match_regex", "")).strip(),
        "mail_to": str(source.get("mail_to", recipients.get("mail_to", ""))).strip(),
        "mail_cc": str(source.get("mail_cc", recipients.get("mail_cc", ""))).strip(),
        "mail_bcc": str(source.get("mail_bcc", recipients.get("mail_bcc", ""))).strip(),
    }


def load_sources() -> list[dict[str, str]]:
    configured = env("TELEGRAM_SOURCES")
    if configured:
        try:
            raw_sources = json.loads(configured)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"TELEGRAM_SOURCES is not valid JSON: {exc}") from exc
        if not isinstance(raw_sources, list) or not raw_sources:
            raise SystemExit("TELEGRAM_SOURCES must be a non-empty JSON array")
        sources = []
        for index, source in enumerate(raw_sources, start=1):
            if not isinstance(source, dict):
                raise SystemExit(f"TELEGRAM_SOURCES item {index} must be an object")
            if "sources" in source:
                recipients = {
                    "mail_to": str(source.get("mail_to", "")).strip(),
                    "mail_cc": str(source.get("mail_cc", "")).strip(),
                    "mail_bcc": str(source.get("mail_bcc", "")).strip(),
                }
                raw_group_sources = source.get("sources")
                if not recipients["mail_to"]:
                    raise SystemExit(f"TELEGRAM_SOURCES group {index} needs mail_to")
                if not isinstance(raw_group_sources, list) or not raw_group_sources:
                    raise SystemExit(f"TELEGRAM_SOURCES group {index} needs a non-empty sources array")
                for source_index, group_source in enumerate(raw_group_sources, start=1):
                    if not isinstance(group_source, dict):
                        raise SystemExit(f"TELEGRAM_SOURCES group {index} source {source_index} must be an object")
                    parsed = source_with_recipients(group_source, recipients)
                    if not parsed["chat_id"] or not parsed["match_regex"]:
                        raise SystemExit(
                            f"TELEGRAM_SOURCES group {index} source {source_index} needs chat_id and match_regex"
                        )
                    sources.append(parsed)
                continue

            parsed = source_with_recipients(source)
            if not parsed["chat_id"] or not parsed["match_regex"]:
                raise SystemExit(f"TELEGRAM_SOURCES item {index} needs chat_id and match_regex")
            sources.append(parsed)
        return sources

    chat_id = env("TELEGRAM_CHAT_ID")
    match_regex = env("MATCH_REGEX")
    if chat_id and match_regex:
        return [{"chat_id": chat_id, "match_regex": match_regex, "mail_to": "", "mail_cc": "", "mail_bcc": ""}]
    raise SystemExit("Set TELEGRAM_SOURCES, or set both TELEGRAM_CHAT_ID and MATCH_REGEX")


def recipient_key(source: dict[str, str]) -> str:
    mail_to = source.get("mail_to", "")
    if not mail_to:
        return "default"
    return "|".join([mail_to, source.get("mail_cc", ""), source.get("mail_bcc", "")])


def notification_identity(source: dict[str, str], pdf_key: str) -> str:
    if not source.get("mail_to"):
        return pdf_key
    return f"{recipient_key(source)}::{pdf_key}"


async def scan_source(
    client: Client,
    chat_id: str,
    chat_sources: list[dict[str, str]],
    state: dict[str, Any],
    download_dir: Path,
    scan_limit: int,
    lookback_messages: int,
    reply_limit: int,
    max_processed: int,
    flags: int,
    scan_from_message_id: int,
) -> list[dict[str, Any]]:
    compiled_sources = [(source, re.compile(source["match_regex"], flags)) for source in chat_sources]

    chat_state = state.setdefault("chats", {}).setdefault(chat_id, {})
    processed = list(dict.fromkeys(chat_state.get("processed", [])))
    processed_set = set(processed)
    items: list[dict[str, Any]] = []
    max_seen = scan_from_message_id

    history = []
    async for message in client.get_chat_history(chat_id, limit=scan_limit):
        history.append(message)
    history.sort(key=lambda msg: msg.id)
    if history:
        max_seen = max(max_seen, max(msg.id for msg in history))

    recent_ids = {msg.id for msg in history[-lookback_messages:]} if lookback_messages > 0 else set()
    candidates = [msg for msg in history if msg.id > scan_from_message_id or msg.id in recent_ids]

    for message in candidates:
        thread_messages = [message]
        thread_messages.extend(await get_replies(client, chat_id, message.id, reply_limit))

        pdf_messages = []
        source_matches: list[tuple[dict[str, str], list[dict[str, Any]]]] = []
        for source, pattern in compiled_sources:
            matches = []
            for idx, thread_message in enumerate(thread_messages):
                location = "main" if idx == 0 else "comment"
                found = match_info(pattern, thread_message, location)
                if found:
                    matches.append(found)
            if matches:
                source_matches.append((source, matches))

        for thread_message in thread_messages:
            if is_pdf(thread_message):
                pdf_messages.append(thread_message)

        if not source_matches or not pdf_messages:
            continue

        for pdf_message in pdf_messages:
            pdf_key = pdf_identity(chat_id, pdf_message)
            downloaded_path: str | None = None
            stat = None
            document = pdf_message.document
            for source, matches in source_matches:
                key = notification_identity(source, pdf_key)
                if key in processed_set:
                    continue
                if downloaded_path is None:
                    downloaded_path = await download_pdf(client, pdf_message, chat_id, download_dir)
                    stat = Path(downloaded_path).stat()
                item = {
                    "key": key,
                    "pdf_key": pdf_key,
                    "mail_to": source.get("mail_to", ""),
                    "mail_cc": source.get("mail_cc", ""),
                    "mail_bcc": source.get("mail_bcc", ""),
                    "chat_id": chat_id,
                    "source_message_id": message.id,
                    "pdf_message_id": pdf_message.id,
                    "file_name": getattr(document, "file_name", None) or Path(downloaded_path).name,
                    "file_size": stat.st_size,
                    "path": str(Path(downloaded_path).relative_to(REPO_ROOT)).replace("\\", "/"),
                    "matches": matches,
                }
                items.append(item)
                processed.append(key)
                processed_set.add(key)

    chat_state["last_message_id"] = max_seen
    chat_state["processed"] = processed[-max_processed:]
    print(f"{chat_id}: found {len(items)} pending PDF file(s)")
    return items


def group_sources_by_chat(sources: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = {}
    for source in sources:
        grouped.setdefault(source["chat_id"], []).append(source)
    return grouped


async def scan() -> None:
    api_id = env_int("TELEGRAM_API_ID", 0)
    api_hash = env("TELEGRAM_API_HASH")
    if not api_id or not api_hash:
        raise SystemExit("TELEGRAM_API_ID and TELEGRAM_API_HASH are required")
    sources = load_sources()

    state_file = REPO_ROOT / env("STATE_FILE", "state/pdf-mail-state.json")
    next_state_file = REPO_ROOT / env("NEXT_STATE_FILE", "run/next-state.json")
    manifest_file = REPO_ROOT / env("MANIFEST_FILE", "run/pending-mails.json")
    download_dir = REPO_ROOT / env("DOWNLOAD_DIR", "downloads")
    session_dir = REPO_ROOT / env("SESSION_DIR", "sessions")
    scan_limit = env_int("SCAN_LIMIT", 200)
    lookback_messages = env_int("LOOKBACK_MESSAGES", 30)
    reply_limit = env_int("DISCUSSION_REPLY_LIMIT", 100)
    max_processed = env_int("MAX_PROCESSED_KEYS", 5000)

    flags = re.MULTILINE
    if env("MATCH_IGNORE_CASE", "true").lower() != "false":
        flags |= re.IGNORECASE

    state = load_json(state_file, {"version": 1, "chats": {}})
    sources_by_chat = group_sources_by_chat(sources)
    scan_from_by_chat = {
        chat_id: int(state.setdefault("chats", {}).setdefault(chat_id, {}).get("last_message_id", 0))
        for chat_id in sources_by_chat
    }

    prepare_session_file(session_dir)
    client_kwargs: dict[str, Any] = {
        "api_id": api_id,
        "api_hash": api_hash,
        "workdir": str(session_dir),
    }
    session_string = env("TELEGRAM_SESSION_STRING")
    bot_token = env("TELEGRAM_BOT_TOKEN")
    if session_string:
        client_kwargs["session_string"] = session_string
    elif bot_token:
        client_kwargs["bot_token"] = bot_token

    download_dir.mkdir(parents=True, exist_ok=True)
    items: list[dict[str, Any]] = []

    async with Client("pdf_mail", **client_kwargs) as client:
        for chat_id, chat_sources in sources_by_chat.items():
            items.extend(
                await scan_source(
                    client,
                    chat_id,
                    chat_sources,
                    state,
                    download_dir,
                    scan_limit,
                    lookback_messages,
                    reply_limit,
                    max_processed,
                    flags,
                    scan_from_by_chat[chat_id],
                )
            )

    write_json(next_state_file, state)
    write_json(manifest_file, {"items": items})
    print(f"found {len(items)} total pending PDF file(s)")


if __name__ == "__main__":
    asyncio.run(scan())
