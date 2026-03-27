# Slack-Enterprise-Data-Retention

This guide provides an overview and instructions for using the `main.py` script to automate administrative tasks for Slack channels.

#### **Overview**

This script is designed for use in a **Slack Enterprise Grid** environment. It reads a list of channel names from a CSV file and performs the following actions for each channel:

1.  **Finds the Channel ID:** It searches for the channel's ID using its name. If a duplicate name is found, the channel is skipped. This only happens when a channel name is provided.
2.  **Invites the Bot:** It uses an Admin API method to invite the bot to the channel. This is necessary to ensure the bot has permission to perform subsequent actions, especially in private channels.
3.  **Sets Custom Retention:** It applies a hardcoded custom data retention policy (e.g., 30 days) to the channel.
4.  **Adds Bot to Posting Permissions:** It modifies the channel's posting permissions to include the bot, which prevents the bot from being blocked from updating the description.
5.  **Updates Channel Description:** It appends a message containing the retention policy to the channel's purpose/description.

#### **Prerequisites**

Before running the script, ensure you have the following:

1.  **Python Environment:** Python 3.12 or newer.
2.  **Required Libraries:**
      * `pandas`
      * `slack_bolt`
      * `slack-sdk`
      * `python-dotenv`
        You can install them by running:
        `pip install pandas slack_bolt python-dotenv slack-sdk`
3.  **CSV File:** A file named `channel_ids.csv` must be in the same directory as the script. It must contain a single column named `channel_id` with the ids or names of the channels you want to process.
4.  **Slack App Setup:**
      * Your bot's app must be installed at the **Organization Level**.
      * The bot token must have the following **Bot Token Scopes** granted:
          * `admin.conversations:read` (for reading channel prefs and retention)
          * `admin.conversations:write` (for inviting the bot and setting prefs)
          * `channels:read`, `groups:read` (for reading channel info)
          * `channels:write`, `groups:write` (for setting channel purpose)
          * `team:read` (for reading workspace defaults)
5.  **Environment Variables:** Create a `.env` file in the project directory with the following variables:
    ```ini
    SLACK_SIGNING_SECRET = "Found in Oauth & Permissions"
    SLACK_BOT_TOKEN = "Your bot token with bot scopes"
    SLACK_USER_TOKEN = "Your bot user token with admin scopes"
    SLACK_BOT_USER_ID = "Your bot's member ID/User ID (starts with U)"
    ```

#### **How to Use the Script**

1.  Place the `main.py` script and `channel_names.csv` in the same directory. If you need to exclude channels, make sure you've included them in `exclude_channels.csv`.
2.  Set up your `.env` file with the correct environment variables.
3.  Execute the script from your terminal:
    ```bash
    python3 main.py
    ```
4.  The script will prompt you to confirm the actions before it proceeds.
    * Do you want to apply data retention policy to all channels? (yes/no)
    * The rentation policy will be set to {DEFAULT_RETENTION_DURATION_DAYS} days. Do you want to proceed? (yes/no)
    * Are you ready to update channel descriptions without applying data retention policy? (yes/no)

#### **Core Functions**

  * `get_channel_id_by_name(channel_name, workspace_id)`: A crucial helper function that correctly finds a channel's ID. It handles cases where multiple channels have the same name by skipping them and logging a warning.
  * XXXXXXX`invite_bot_to_channel(channel_id, bot_user_id, workspace_id)`: Uses `admin.conversations.invite` to add the bot to a channel, which is necessary for it to perform other actions.
  * `apply_custom_retention_policy(channel_id, duration_days)`: Sets the message retention for a channel using `admin.conversations.setCustomRetention`.
  * `update_channel_posting_permissions_for_bot(channel_id, bot_user_id, workspace_id)`: Modifies a channel's posting permissions to include the bot, while preserving existing permissions.
  * `update_channel_description_with_retention(channel_id, new_message)`: Appends a message to the channel's purpose/description. This function uses a helper to enforce the **250-character limit** and a regular expression to avoid duplicate retention messages.
  * `process_channel(channel_id, bot_user_id, workspace_id)`: Orchestrates the entire workflow for a single channel.

#### **Logging & Troubleshooting**

  * All actions and errors are logged to `slack_channel_automation.log` for auditing.
  * The script includes a delay (`API_CALL_DELAY_SECONDS`) between API calls to prevent hitting Slack's rate limits, especially with a large number of channels.
  * If a channel name has duplicates in your organization, the script will log a warning and skip that channel to prevent an ambiguous update.
  * If the bot is already a member of a channel, the `invite_bot_to_channel` function will handle this gracefully and continue without errors.

-----