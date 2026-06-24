# Telegram PDF Mail

GitHub Actions workflow that scans a Telegram chat/channel on a schedule, matches message text, captions, hashtags, filenames, and discussion comments with a regular expression, downloads matching PDF documents, and sends each PDF as a separate email attachment.

The workflow does not commit Telegram sessions, SMTP credentials, downloaded files, or generated runtime files. It only commits `state/pdf-mail-state.json` after a successful run.

## Required Secrets

Set these in **Settings -> Secrets and variables -> Actions -> Secrets**:

- `TELEGRAM_API_ID`
- `TELEGRAM_API_HASH`
- `TELEGRAM_SESSION_STRING` or `TELEGRAM_SESSION_FILE_B64` or `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `MATCH_REGEX`
- `SMTP_SERVER`
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `MAIL_FROM`
- `MAIL_TO`

Optional mail secrets:

- `SMTP_PORT` defaults to `465`
- `SMTP_SECURE` defaults to `true`
- `MAIL_CC`
- `MAIL_BCC`

## Optional Variables

Set these in **Settings -> Secrets and variables -> Actions -> Variables** when needed:

- `SCAN_LIMIT` defaults to `200`
- `LOOKBACK_MESSAGES` defaults to `30`
- `DISCUSSION_REPLY_LIMIT` defaults to `100`
- `MATCH_IGNORE_CASE` defaults to `true`
- `MAIL_SUBJECT_PREFIX` defaults to `Telegram PDF`
- `ZIP_THRESHOLD_MB` defaults to `45`
- `SMTP_MAX_ATTACHMENT_MB` defaults to `0`, meaning no explicit post-zip size check

`MATCH_REGEX` is a normal Python regular expression. Hashtags are just text, so a rule such as `#资料|#pdf|invoice` works.

## Schedule

The default schedule is `10 15 * * *`, which runs once per day at 00:10 Japan time. Edit `.github/workflows/pdf-mail.yml` if a different schedule is needed.

## State Behavior

The scanner writes a pending manifest to `run/pending-mails.json` and a proposed next state to `run/next-state.json`.

- If no PDFs are pending, the workflow commits the new scan state.
- If PDFs are pending, the workflow sends one email per PDF first.
- After all emails succeed, it commits the full next state.
- If only some emails succeed, it records only those successful PDF keys and does not advance the last scanned message id.
- Failed PDFs remain unprocessed so a later run can retry them.

`LOOKBACK_MESSAGES` rechecks recent channel messages so comments added after a previous scan can still be matched.
