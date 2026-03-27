# Enterprise Data Retention Slack App

## Installation

#### Create a Slack App
1. Open [https://api.slack.com/apps/new](https://api.slack.com/apps/new) and choose "From an app manifest"
2. Choose the workspace you want to install the application to
3. Copy the contents of [manifest.json](./manifest.json) into the text box that says `*Paste your manifest code here*` (within the JSON tab) and click *Next*
4. Review the configuration and click *Create*
5. Click *Install to Workspace* and *Allow* on the screen that follows. You'll then be redirected to the App Configuration dashboard.

> Note: Because this app uses admin scopes, it must be installed at the org level on Enterprise Grid by an Org Admin/Owner.

#### Environment Variables
Before you can run the app, you'll need to store some environment variables.

1. Open your app configuration and go to **OAuth & Permissions** to copy the Bot User OAuth Token.
2. Install the app at org level with admin scopes and obtain the admin-capable user token used for `admin.*` API calls.
3. Get the bot user ID for the installed app user (for posting-permission updates).
4. Optionally set an app-level token if you plan to use socket mode or future app-level workflows.

This project requires both a bot token and a user token.

Create a `.env` file in the project root with:

```env
SANDBOX_SLACK_BOT_TOKEN=<your-bot-token>
SANDBOX_SLACK_USER_TOKEN=<your-user-token-with-admin-scopes>
SANDBOX_SLACK_BOT_USER_ID=<your-bot-user-id>
# Optional in current code path
SANDBOX_SLACK_APP_TOKEN=<your-app-level-token>
```

### Setup Your Local Project
```zsh
# Clone this project onto your machine
git clone https://github.com/slack-samples/bolt-python-starter-template.git

# Change into this project directory
cd bolt-python-starter-template

# Setup your python virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install the dependencies
pip install -r requirements.txt

# Start your local server
python3 app.py
```

## Project Structure

### `manifest.json`

`manifest.json` is a configuration for Slack apps. With a manifest, you can create an app with a pre-defined configuration, or adjust the configuration of an existing app.

### `app.py`

`app.py` is the entry point for the application and is the file you'll run to start the server. This project aims to keep this file as thin as possible, primarily using it as a way to route inbound requests.

### `channel_export/`

`channel_export/` is required and should contain export files from each workspace.

If you will be updating this GitHub repository, ensure `.gitignore` includes `.env` so tokens are not pushed.

## Script Purpose and Workflow

### TLDR
1. Iterate over a list of channels.
2. Apply a custom data retention policy on each target channel.
3. Apply a label to the channel description with the data retention policy that was applied.

### Detailed Purpose
This script automates Slack channel governance tasks for Enterprise Grid by processing channel export CSV files, filtering target channels, applying retention settings through Slack Admin APIs, and synchronizing each channel's description with a retention label.

### End-to-End Workflow
1. Load environment variables, configure SSL, initialize logging, and create the Slack API client.
2. Read CSV exports from `channel_export/`.
3. Filter channels by naming rule, creator rule, and creation year.
4. Write filtered channels to `filtered_channels.csv`.
5. For each filtered channel:
	 1. Apply the custom retention policy.
	 2. Skip description updates for archived channels.
	 3. Attempt bot invite and posting-permission updates.
	 4. Update description with exactly one retention label.

### Inputs, Outputs, and Artifacts
Inputs:
- CSV files in `channel_export/`
- Environment variables:
	- `SANDBOX_SLACK_BOT_TOKEN`
	- `SANDBOX_SLACK_USER_TOKEN`
	- `SANDBOX_SLACK_BOT_USER_ID`
	- `SANDBOX_SLACK_APP_TOKEN` (optional in current flow)

Outputs:
- `filtered_channels.csv`
- Retention policy updates in Slack
- Channel description label updates in Slack
- Runtime logs in `slack_channel_automation.log`

## Function and Class Reference (`app.py`)

### `ChannelFilter`
- `filter_by_creator(creator_id, target_creator_id) -> bool`
	- Returns `True` when a channel creator matches the target creator id.
- `filter_by_name_prefix(channel_name, prefix) -> bool`
	- Returns `True` when a channel name starts with the specified prefix (case-insensitive).

### `TextUtilities`
- `remove_data_retention_substrings(text) -> str`
	- Removes existing retention substrings from description text.
- `count_data_retention_occurrences(text) -> int`
	- Counts how many retention labels are present in a description.
- `create_description(clean_description_text, message_to_append) -> str`
	- Creates the final description and truncates safely to Slack's length constraint.
- `format_user_ids_for_set_prefs(user_id_list) -> str`
	- Converts user ids into the Slack `who_can_post` format (`user:U...`).

### `SlackChannel`
- `__init__(channel_id, client=None, retention_years=None)`
	- Initializes channel context, retention target, credentials, and API client.
- `add_bot_to_channel() -> bool`
	- Invites the bot user into a channel through an admin API call.
- `search_for_channel() -> dict | None`
	- Finds channel metadata using `admin_conversations_search`.
- `get_channel_info() -> dict | None`
	- Fetches channel details from `conversations_info`.
- `update_retention_policy() -> bool`
	- Applies custom retention with days derived from `retention_years * 365`.
- `get_retention_policy() -> dict | None`
	- Fetches current retention policy for a channel.
- `update_channel_description(new_description) -> bool`
	- Updates channel purpose text through `conversations_setPurpose`.
- `get_posting_permissions() -> dict | None`
	- Reads posting preferences via `admin_conversations_getConversationPrefs`.
- `update_posting_permissions(prefs_payload) -> bool`
	- Writes posting preferences via `admin_conversations_setConversationPrefs`.

### `PostingPermissionsManager`
- `__init__(bot_user_id)`
	- Stores the bot user id used for permission updates.
- `apply_posting_permissions(conversation) -> bool`
	- Ensures bot user can post when channel posting is restricted, then writes updated prefs.

### `DescriptionManager`
- `update_with_retention(conversation) -> bool`
	- Ensures the description has exactly one correct retention label by cleaning old labels, rebuilding text, and updating Slack.

### `ChannelWorkflow`
- `__init__(bot_user_id=..., client=None)`
	- Initializes managers and API client used in the end-to-end per-channel workflow.
- `process_channel(channel_id, retention_years) -> bool`
	- Main orchestration function for each channel: retention first, then description workflow.
- `_update_description_workflow(conversation) -> bool`
	- Internal sequence: check archived state, add bot, adjust permissions, update description, and log retention state.

### `CSVProcessor`
- `__init__(file_path)`
	- Stores CSV path for processing.
- `read_csv_data()`
	- Reads full CSV into a list of dictionaries.
- `filter_relavent_columns(*columns)`
	- Reads required columns and validates they exist.
- `write_csv_data(data, output_file_path)`
	- Writes or appends CSV rows and normalizes selected columns (`Private`, `Archived`).

### `apply_data_retention_workflow_to_channels(csv_from_processor, retention_years, client)`
Batch processor that applies retention workflow:
1. Creates a `ChannelWorkflow` instance.
2. Iterates the input channel list and calls `process_channel()` for each channel.
3. Extracts channel ID from each dict row and passes retention years to the workflow.

### `process_secinc_channels(channel_export_directory, output_file) -> list[dict]`
Orchestrates CSV discovery and filtering:
1. Scans all CSV files in the specified directory.
2. Filters by name prefix (`secinc-`), creator id (`firefighter_id`), and creation year (`2025`).
3. Normalizes date formatting to `YYYY-MM-DD HH:MM:SS`.
4. Writes cumulative results to output CSV file in append mode.
5. Returns list of matched channel dictionaries.

### `main()`
Entry point that:
1. Calls `process_secinc_channels("channel_export", "filtered_channels.csv")` to read and filter channels.
2. Calls `apply_data_retention_workflow_to_channels()` with filtered channels to apply retention policy and update descriptions.

### Important Behavioral Notes
1. Retention years are hardcoded in `main()`, while creator id, prefix, and year filter are hardcoded in `process_secinc_channels()`.
2. Bot invite and posting permission updates are non-blocking in the description phase; description update is the blocking step.
3. Archived channels skip description updates.
4. The script expects Enterprise Grid admin-level permissions to run successfully for admin API calls.
5. `SANDBOX_SLACK_APP_TOKEN` is currently loaded but not used by the active execution path.