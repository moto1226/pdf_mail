# Telegram PDF Mail

GitHub Actions workflow that scans a Telegram chat/channel on a schedule, matches message text, captions, hashtags, filenames, and discussion comments with a regular expression, downloads matching PDF documents, saves them into this GitHub repository, and sends one email with raw GitHub download links.

The workflow does not commit Telegram sessions, SMTP credentials, or generated runtime files. It commits matched PDFs under `files/` and updates `state/pdf-mail-state.json` after a successful notification.

## Required Secrets

Set these in **Settings -> Secrets and variables -> Actions -> Secrets**:

- `TELEGRAM_API_ID`
- `TELEGRAM_API_HASH`
- `TELEGRAM_SESSION_STRING` or `TELEGRAM_SESSION_FILE_B64` or `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_SOURCES`, or the legacy pair `TELEGRAM_CHAT_ID` and `MATCH_REGEX`
- `SMTP_SERVER`
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `MAIL_FROM`
- `MAIL_TO`, unless every `TELEGRAM_SOURCES` group has its own `mail_to`

Optional mail secrets:

- `SMTP_PORT` defaults to `465`
- `SMTP_SECURE` defaults to `true`
- `SMTP_STARTTLS` defaults to `false` and is only used when `SMTP_SECURE` is `false`
- `MAIL_CC`
- `MAIL_BCC`

## Optional Variables

Set these in **Settings -> Secrets and variables -> Actions -> Variables** when needed:

- `SCAN_LIMIT` defaults to `200`
- `LOOKBACK_MESSAGES` defaults to `30`
- `DISCUSSION_REPLY_LIMIT` defaults to `100`
- `MATCH_IGNORE_CASE` defaults to `true`
- `MAIL_SUBJECT_PREFIX` defaults to `PDF 更新`
- `PDF_REPO_DIR` defaults to `files`
- `PUBLIC_BASE_URL` defaults to the current repository raw URL
- `MAX_REPO_FILE_MB` defaults to `95`, to stay below GitHub's 100 MiB hard file limit

Use `TELEGRAM_SOURCES` to scan multiple chats with different regular expressions and send all matches to the default `MAIL_TO`:

```json
[
  {
    "chat_id": "QiKan2026",
    "match_regex": "财新周刊|财新"
  },
  {
    "chat_id": "AnotherChannel",
    "match_regex": "#资料|#pdf|课程"
  }
]
```

Use grouped `TELEGRAM_SOURCES` when different chats or keywords should notify different recipients:

```json
[
  {
    "mail_to": "a@example.com",
    "sources": [
      {
        "chat_id": "QiKan2026",
        "match_regex": "财新周刊|财新"
      },
      {
        "chat_id": "AnotherChannel",
        "match_regex": "#资料|#pdf|课程"
      }
    ]
  },
  {
    "mail_to": "b@example.com,c@example.com",
    "sources": [
      {
        "chat_id": "MagazineChannel",
        "match_regex": "经济学人|The Economist"
      }
    ]
  }
]
```

`mail_cc` and `mail_bcc` can also be set on each group. If the same PDF matches multiple recipient groups, each group receives its own notification while the PDF file is saved only once.
Sources are grouped by `chat_id` at runtime, so the workflow fetches each Telegram chat once per run even if that chat appears in multiple recipient groups.

For a single chat, the legacy `TELEGRAM_CHAT_ID` and `MATCH_REGEX` secrets still work. `MATCH_REGEX` is a normal Python regular expression. Hashtags are just text, so a rule such as `#资料|#pdf|invoice` works.

## Schedule

The default schedule is `10 15 * * *`, which runs once per day at 00:10 Japan time. Edit `.github/workflows/pdf-mail.yml` if a different schedule is needed.

## State Behavior

The scanner writes a pending manifest to `run/pending-mails.json` and a proposed next state to `run/next-state.json`.

- If no PDFs are pending, the workflow commits the new scan state.
- If PDFs are pending, the workflow copies files within `MAX_REPO_FILE_MB` into `files/`, generates raw GitHub download links, and sends one notification email.
- PDFs over `MAX_REPO_FILE_MB` are not committed to the repository. They are listed as skipped in the email and marked as processed only after that email is sent successfully.
- After the notification succeeds, it commits the PDFs and the full next state.
- PDF files are committed and pushed one at a time, then the state file is committed last. This keeps each GitHub push smaller when one run finds several PDFs.
- If copying or SMTP notification fails, it does not commit new PDFs or mark unsent items as processed, so a later run can retry.

`LOOKBACK_MESSAGES` rechecks recent channel messages so comments added after a previous scan can still be matched.

The repository must be public if recipients should download raw links without logging in. PDFs are kept in Git history; this workflow does not delete or expire old files.
