# Notifications

All settings are environment variables, so secrets never sit in `jobveyra.yml`.

## Daily email digest

`jobveyra newsletter build` writes the email to `reports/newsletter/`;
`jobveyra newsletter send` sends it when these are set:

| Variable | Value |
|---|---|
| `SMTP_HOST` | Mail server, for example `smtp.gmail.com` |
| `SMTP_PORT` | Optional, default `587` (STARTTLS) |
| `SMTP_USER` | Sending account |
| `SMTP_PASSWORD` | Its password or app password |
| `NEWSLETTER_TO` | Recipients, comma-separated |
| `NEWSLETTER_FROM` | Optional, defaults to `SMTP_USER` |

Without them, `send` reports what is missing and sends nothing. `--dry-run` writes the
complete message to `newsletter.eml` for inspection.

To schedule it, run both commands from cron, a systemd timer, or a GitHub Actions workflow
in a **private** repository that holds your workspace.

## Telegram

Set `notify.telegram_enabled: true` and the variables `TELEGRAM_BOT_TOKEN` and
`TELEGRAM_CHAT_ID`. `jobveyra notify` sends the digest summary, or any text you pass.

## Slack, Discord, Teams

Create an incoming webhook and put its URL in the variable named by `notify.webhook_env`
(default `JOBVEYRA_WEBHOOK`). The same `jobveyra notify` command posts to it.
