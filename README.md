# Telegram PDF Mail

GitHub Actions workflow that scans a Telegram chat/channel on a schedule, matches message text, captions, hashtags, filenames, and discussion comments with a regular expression, downloads matching PDF documents, uploads them to a private Cloudflare R2 bucket, and sends one email with presigned download links.

The workflow does not commit Telegram sessions, SMTP credentials, downloaded files, or generated runtime files. It only commits `state/pdf-mail-state.json` after a successful run.

## Required Secrets

Set these in **Settings -> Secrets and variables -> Actions -> Secrets**:

- `TELEGRAM_API_ID`
- `TELEGRAM_API_HASH`
- `TELEGRAM_SESSION_STRING` or `TELEGRAM_SESSION_FILE_B64` or `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `MATCH_REGEX`
- `R2_ACCOUNT_ID`
- `R2_ACCESS_KEY_ID`
- `R2_SECRET_ACCESS_KEY`
- `R2_BUCKET`
- `SMTP_SERVER`
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `MAIL_FROM`
- `MAIL_TO`

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
- `MAIL_SUBJECT_PREFIX` defaults to `Telegram PDF`
- `R2_KEY_PREFIX` defaults to `telegram-pdfs/`
- `R2_URL_EXPIRES_SECONDS` defaults to `604800`, the 7-day maximum for R2 presigned URLs

`MATCH_REGEX` is a normal Python regular expression. Hashtags are just text, so a rule such as `#资料|#pdf|invoice` works.

## Schedule

The default schedule is `10 15 * * *`, which runs once per day at 00:10 Japan time. Edit `.github/workflows/pdf-mail.yml` if a different schedule is needed.

## State Behavior

The scanner writes a pending manifest to `run/pending-mails.json` and a proposed next state to `run/next-state.json`.

- If no PDFs are pending, the workflow commits the new scan state.
- If PDFs are pending, the workflow uploads all PDFs to R2, generates presigned download links, and sends one notification email.
- After upload and email notification succeed, it commits the full next state.
- If R2 upload or SMTP notification fails, it does not mark those PDFs as processed, so a later run can retry.

`LOOKBACK_MESSAGES` rechecks recent channel messages so comments added after a previous scan can still be matched.

The R2 bucket should stay private. The emailed presigned URLs allow anyone with the link to download the file until the configured expiration time.
