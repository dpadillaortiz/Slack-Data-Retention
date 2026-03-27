# Slack Channel Data Retention Automation

This repository contains a small automation that applies and documents Slack channel message retention policies at scale. 

The primary entrypoint is `main.py`, which reads a CSV of channels and retention policies, applies a custom retention policy to each channel using the Slack admin APIs, updates the channel description/purpose with a retention label, and adjusts posting permissions for the bot as needed.

## What it does
- Reads a CSV file of channels and their desired retention (years).
- For each channel it:
  - Applies the custom retention policy via Slack admin API.
  - Ensures the bot is a member of the channel (invites it if necessary).
  - Updates the channel purpose/description with a `(Data retention : X Years)` label (handles truncation and cleans up existing labels).
  - Adjusts posting permissions to include the bot where required.
- Logs progress and errors to `slack_channel_automation.log` and stdout.

## Prerequisites
- Python 3.9+ (project uses `asyncio` and modern libs)
- The following Python packages (suggested):
  - pandas
  - slack-bolt
  - slack-sdk
  - python-dotenv

You can install these with pip:

```bash
python -m venv .venv
source .venv/bin/activate
pip install pandas slack-bolt slack-sdk python-dotenv
```

(If you prefer a `requirements.txt`, add the packages above and pin versions.)

## Configuration
There are two configuration approaches used by the script:

1. Environment & `.env`
   - `SLACK_BOT_USER_ID` is read from environment (or `.env`). This should be the Bot/User ID used for admin API actions.
   - The project uses `python-dotenv` and will load variables from a `.env` file when present.

2. `aws_secrets.py` helper
   - The code expects an `aws_secrets` module (present in this repository) exposing functions used to fetch JSON strings containing Slack secrets:
     - `aws_secrets.get_signing_secret()` -> JSON string containing signing secret
     - `aws_secrets.get_bot_token()` -> JSON string containing bot token
     - `aws_secrets.get_user_token()` -> JSON string containing user token
   - `main.py` expects these to be JSON strings that are then parsed, for example:
     - json.loads(aws_secrets.get_signing_secret())["EDR_SIGNING_SECRET_A09A7PN57N0"]
     - json.loads(aws_secrets.get_bot_token())["EDR_BOT_TOKEN_A09A7PN57N0"]
     - json.loads(aws_secrets.get_user_token())["EDR_USER_TOKEN_A09A7PN57N0"]

If you don't use `aws_secrets`, you can replace those calls with reading tokens directly from environment variables.

### Required environment variables (example)
- SLACK_BOT_USER_ID=A0123456789
- Optionally you may have a `.env` file with that variable.

## CSV format
The script expects a CSV file named `channel_ids.csv` (or set `CSV_FILE_PATH` at top of `main.py`) with headers:

- `channel_id` — Slack channel ID (e.g., `C0123456789`)
- `retention` — retention period in years (integer or float). Optional; if blank or unparsable the script uses the default retention value.

Example `channel_ids.csv`:

```csv
channel_id,retention
C08T5BBGTH8,7
C08T5BCANF4,7
C08TZDGSELQ,3
C09A88K3SLC,2
C099SC9PEQ7,
```

Notes:
- `retention` is interpreted as years and converted to days (years * 365).
- Duplicate `channel_id` rows are ignored after the first occurrence (first occurrence's retention is used).

## Defaults & constants
- Default retention (used when parsing fails/missing): `DEFAULT_RETENTION_DURATION_DAYS` in `main.py` (set in code).
- Slack description max length handled by `CHANNEL_DESCRIPTION_MAX_LENGTH` (250 characters).
- `API_CALL_DELAY_SECONDS` introduces small sleeps between Slack API calls to help respect rate limits.

## Running the script
1. Ensure your environment variables / `.env` and `aws_secrets` are configured.
2. Prepare `channel_ids.csv` in the repository root (or update `CSV_FILE_PATH`).
3. Run:

```bash
python main.py
```

The script is asynchronous and runs `asyncio.run(main())` when executed directly.

## Logging
- Logs are written to `slack_channel_automation.log` in the repository root and also printed to stdout.

## Safety & behavior notes
- The script invokes admin Slack API endpoints (invite bot to channels, set custom retention, set conversation prefs). Make sure the tokens used have the necessary admin scopes.
- The script swallows exceptions inside per-channel operations and logs errors; it attempts to continue processing other channels when possible.
- The script will attempt to invite the bot and update permissions; ensure the tokens used are appropriate and you understand the scope of changes.

## Troubleshooting
- Missing `channel_id`/`retention` headers: the script will log an error and skip processing.
- FileNotFoundError when `channel_ids.csv` is missing: the script will create a small dummy CSV if one is not present when run directly (see `main.py`).
- If Slack API calls fail, check tokens and scopes and inspect `slack_channel_automation.log` for details.

## Extending or modifying
- If you prefer to store secrets in environment variables rather than `aws_secrets`, replace the `aws_secrets` calls in `main.py` with `os.getenv(...)` and provide those values in a `.env` or environment.
- You can change retention units (years -> months/days) by modifying the CSV parser in `read_channel_ids_from_csv`.

## License
This repo does not include a license file. Add a LICENSE if you intend to open source or share.

---
Generated from `main.py` (automatically summarized). 