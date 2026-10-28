# VOX watcher

Watches VOX Egypt listings and sends Telegram alerts when movies are added,
booking opens or reopens, or showtimes appear at additional cinemas.

## Run

Use Python 3.12 and install `pip install -r requirements.txt`. Configure
`TELEGRAM_TOKEN` with your bot token and optionally `TELEGRAM_CHAT_ID` with an
owner chat ID, in the environment or a local `.env` file. In GitHub Actions,
set these as repository secrets. `WATCH_CINEMAS` is an optional comma-separated
cinema filter (a repository variable in Actions).

Run `python vox.py` for one check, or `python vox.py --test` for a live site and
Telegram check. Both commands process pending bot subscriptions. The Actions
workflow runs every five minutes, though GitHub may delay scheduled jobs.

Booking alerts track the latest successful observation, including Now Showing
movies. A closed observation resets the alert so the next opening sends another
message. An unchanged opening does not send repeated alerts; failed deliveries
are retried on the next check (recipients who already received it may see a
duplicate). The first run after this update rechecks old “already alerted” state
and alerts for currently available bookings. Changes that both open and close
between checks cannot be detected.

## Telegram subscriptions

Anyone can open the bot's private chat and send `/start` to subscribe. They receive
a confirmation on the next watcher run, then future alerts. `/stop` unsubscribes.
The configured owner chat remains a recipient via `TELEGRAM_CHAT_ID`.
Telegram only keeps unprocessed bot updates for up to 24 hours: after deploying
this update, send `/start` again if no confirmation arrives.

The watcher polls Telegram `getUpdates`; the same bot must not have an active
webhook or another update consumer. Subscription failures are reported in the
workflow logs without exposing the token.

Subscriber IDs and the Telegram update offset are stored in `subscribers.enc`,
encrypted using a key derived from `TELEGRAM_TOKEN`. Actions commits this file
alongside movie state so subscriptions survive fresh runners. Keep the same bot
token across runners. If the token is rotated, remove the old encrypted file and
ask subscribers to send `/start` again. Never commit `.env` or a plaintext list
of subscribers.

## Tests

Run `python -m unittest discover -s tests -v`. These regression tests use mocked
VOX and Telegram responses; they do not send real messages.
