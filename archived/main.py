import os
import pandas as pd
import json
import logging
import asyncio
# from datetime import timedelta
import re
import aws_secrets

from dotenv import load_dotenv
load_dotenv()

from slack_sdk.errors import SlackApiError
from slack_bolt.async_app import AsyncApp

# --- Configuration ---
CSV_FILE_PATH = 'channel_ids.csv'
LOG_FILE_PATH = 'slack_channel_automation.log'
CHANNEL_DESCRIPTION_MAX_LENGTH = 250 # Slack's hard limit for channel purpose/description
RETENTION_MESSAGE_PREFIX = "Data retention : " # Prefix for the message appended to description #(Data retention : ${durationYears} Years)
DEFAULT_RETENTION_DURATION_DAYS = 3650 # (730 = 2 years)(2555 = 7 years) Example default if channel has no custom policy
API_CALL_DELAY_SECONDS = 0.5 # Delay between API calls to respect Slack rate limits (adjust as needed)

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE_PATH),
        logging.StreamHandler() # Also print to console
    ]
)

# --- Slack API Client Initialization ---
SLACK_SIGNING_SECRET = json.loads(aws_secrets.get_signing_secret())["EDR_SIGNING_SECRET_A09A7PN57N0"]
SLACK_BOT_TOKEN = json.loads(aws_secrets.get_bot_token())["EDR_BOT_TOKEN_A09A7PN57N0"] # Your bot token with admin scopes
SLACK_USER_TOKEN = json.loads(aws_secrets.get_user_token())["EDR_USER_TOKEN_A09A7PN57N0"] # Your bot's User ID (starts with U or A)
SLACK_BOT_USER_ID = os.getenv("SLACK_BOT_USER_ID") # Your bot's User ID (starts with U or A)

app = AsyncApp(
    token=SLACK_BOT_TOKEN,
    signing_secret=SLACK_SIGNING_SECRET
)

# --- Helper Functions ---
def generate_retention_message(retention_policy: str) -> str:
    """
    Generates a retention message based on the channel's custom retention policy.
    Args:
        retention_policy (str): The channel's custom retention policy.
    Returns:
        str: Formatted retention message, or False on error.
    """

    return f"{RETENTION_MESSAGE_PREFIX}{retention_policy} Years"

def remove_data_retention_substrings(text: str) -> str:
    """
    Removes all occurrences of the patterns "(Data retention*)"
    Args:
        text: The input string containing the substrings to be removed.
    Returns:
        The string with all occurrences of the patterns removed.
    """
    # This regex pattern specifically targets the substrings you want to remove.
    # Regex Breakdown:
    # \(Data retention : \s*\d+\s*Years\)          - Matches the numeric pattern.
    # |                                            - The 'OR' operator.
    # \(Data retention : Error retrieving policy.\) - Matches the specific error string.
    pattern = r'\(Data retention.*?\)'
    
    # re.sub() finds all non-overlapping occurrences of the pattern in the text
    # and replaces them with an empty string ('').
    cleaned_text = re.sub(pattern, '', text)
    
    # After removing the patterns, we'll strip any leading/trailing whitespace
    # that might be left over from the replacements.
    return cleaned_text.strip()

def count_data_retention_occurrences(text: str) -> int:
    """
    Counts all occurrences of the patterns "(Data retention*)"
    Args:
        text: The input string to be searched.
    Returns:
        The number of times the pattern was found.
    """
    # The same regex pattern is used to find the occurrences.
    pattern = r'\(Data retention.*?\)'
    
    # re.findall() returns a list of all non-overlapping matches.
    # The length of this list is the number of occurrences.
    matches = re.findall(pattern, text)
    
    return len(matches)

def is_valid_channel_id(channel_id: str) -> bool:
    """
    Return True if `channel_id` looks like a Slack channel ID of type C, G, or D.

    Heuristic rules used:
    - Must be a non-empty string.
    - Must begin with one of: 'C', 'G', or 'D' (case-insensitive).
    - Followed by 8 to 10 letters or digits (total length 9–11 chars).
    - Uses only ASCII letters and digits (no punctuation, spaces, or underscores).

    This is a heuristic validator — Slack's exact ID format is not publicly guaranteed,
    so this function intentionally errs on the side of matching common patterns.
    """
    # Pattern: start with C, G, or D (case-insensitive), then 8–10 alphanumeric characters -> total length 9–11
    channel_id_pattern = re.compile(r'^[CGD][A-Za-z0-9]{8,10}$', re.IGNORECASE)

    if not channel_id or not isinstance(channel_id, str):
        return False
    channel_id = channel_id.strip()
    return bool(channel_id_pattern.match(channel_id))

def has_hyphen_and_underscore(input_string: str) -> bool:
    """
    Checks if a string contains both a hyphen ('-') and an underscore ('_').
    Args:
        input_string: The string to check.
    Returns:
        True if the string contains both characters, False otherwise.
    """
    return '-' in input_string or '_' in input_string

def truncate_description(description_text: str, message_to_append: str, max_length: int) -> str:
    """
    Appends a message to a description, truncating if necessary to stay within max_length.

    Args:
        description_text (str): The original description text.
        message_to_append (str): The message to append to the description.
        max_length (int): The maximum allowed length for the final description.    
    Returns:
        str: The updated description, truncated if necessary.
    """
    no_labels_description = remove_data_retention_substrings(description_text)
    combined_length = len(no_labels_description) + len(message_to_append) + 2
    if combined_length > max_length:
        # Calculate how much of the original description we can keep
        # Subtract 3 for ellipsis "..."
        space_for_original = max_length - len(message_to_append) - 4
        if space_for_original < 0: # Message to append is already too long
            return message_to_append[:max_length] # Just return truncated message
        
        truncated_original = no_labels_description[:space_for_original]
        return f"{truncated_original}...{message_to_append}"
    else:
        return f"{no_labels_description} {message_to_append}"
    
def format_user_ids_for_set_prefs(user_id_list: list) -> str:
    """
    Converts a list of user IDs (e.g., ['U1234', 'U5678'])
    into the format required by admin.conversations.setConversationPrefs
    (e.g., 'user:U1234,user:U5678').
    Args:
        user_id_list (list): List of user IDs as strings.
    Returns:
        str: Comma-separated string formatted for Slack API.
    """
    if not user_id_list:
        return ""
    return ",".join([f"user:{uid}" for uid in user_id_list])

async def read_channel_ids_from_csv(file_path: str) -> list:
    """
    Reads channel IDs and retention values from a specified CSV file.

    Expects the CSV to have headers: 'channel_id' and 'retention'.

    Args:
        file_path (str): The path to the CSV file.
    Returns:
        list: A list of dicts preserving CSV order and unique by channel_id. Each dict has keys:
              - 'channel_id' (str)
              - 'retention_days' (int)  # retention converted to days

    Assumption: the 'retention' column is specified in years (integer). If parsing fails or
    the value is missing, DEFAULT_RETENTION_DURATION_DAYS is used as a fallback.
    """

    def _parse_retention_to_days(val):
        # val is expected to represent years. Return days as int.
        try:
            if pd.isna(val):
                return DEFAULT_RETENTION_DURATION_DAYS
            s = str(val).strip()
            if s == "":
                return DEFAULT_RETENTION_DURATION_DAYS
            years = int(float(s))
            return int(years * 365)
        except Exception:
            logging.warning(f"Unable to parse retention value '{val}' in CSV '{file_path}'. Using default {DEFAULT_RETENTION_DURATION_DAYS} days.")
            return DEFAULT_RETENTION_DURATION_DAYS

    def _read_sync(path: str) -> list:
        df = pd.read_csv(path)
        required = {'channel_id', 'retention'}
        if not required.issubset(set(df.columns)):
            logging.error(f"CSV file '{path}' must contain columns: 'channel_id' and 'retention'. Found: {list(df.columns)}")
            return []

        # Keep only relevant columns and normalize
        df = df[['channel_id', 'retention']].copy()
        df['channel_id'] = df['channel_id'].astype(str).str.strip()
        df = df[df['channel_id'] != ""]

        # Preserve order and dedupe by first occurrence
        seen = {}
        for _, row in df.iterrows():
            cid = row['channel_id']
            if cid in seen:
                continue
            retention_days = _parse_retention_to_days(row['retention'])
            seen[cid] = retention_days

        return [{'channel_id': k, 'retention_days': v} for k, v in seen.items()]

    try:
        channel_entries = await asyncio.to_thread(_read_sync, file_path)
        logging.info(f"Successfully read {len(channel_entries)} unique channel entries from '{file_path}'.")
        return channel_entries
    except FileNotFoundError:
        logging.error(f"CSV file not found at '{file_path}'.")
        return []
    except Exception as e:
        logging.error(f"Error reading CSV file '{file_path}': {e}")
        return []

# --- Core Task Functions ---


async def add_bot_to_channel(channel_id: str, bot_user_id: str) -> bool:
    """
    Attempts to add the bot to the channel.
    Args:
        channel_id (str): The ID of the channel to join.
        bot_user_id (str): The user ID of the bot to invite.
    Returns:
        bool: True if successful, None otherwise.
    """
    try:
        logging.info(f"Attempting to invite bot...")
        await app.client.admin_conversations_invite(
            token=SLACK_USER_TOKEN, # Use user token for admin actions
            channel_id=channel_id,
            user_ids=bot_user_id,
        )
        logging.info(f"Bot invited to channel '{channel_id}' successfully.")
        return True
    except SlackApiError as e:
        logging.error(f"Slack API error in ensure_bot_membership_and_get_info for '{channel_id}': {e.response['error']}")
        return False 
    except Exception as e:
        logging.error(f"Unexpected error in ensure_bot_membership_and_get_info for '{channel_id}': {e}")
        return False
    finally:
        await asyncio.sleep(API_CALL_DELAY_SECONDS) # Respect rate limits

async def get_channel_info(channel_id: str) -> dict:
    """
    Retrieves detailed information about a channel.
    Args:
        channel_id (str): The ID of the channel.
    Returns:
        dict: Channel information if successful, None otherwise.
    """
    try:
        logging.info(f"Fetching channel info for '{channel_id}'...")
        info_response = await app.client.conversations_info(
            channel=channel_id
        )
        logging.info(f"Fetched info for channel '{channel_id}': {info_response['channel']['name']}")
        return info_response["channel"]
    except SlackApiError as e:
        logging.error(f"Slack API error in get_channel_info for '{channel_id}': {e.response['error']}")
        return None 
    except Exception as e:
        logging.error(f"Unexpected error in get_channel_info for '{channel_id}': {e}")
        return None
    finally:
        await asyncio.sleep(API_CALL_DELAY_SECONDS) # Respect rate limits

async def apply_custom_retention_policy(channel_id: str, duration_days: int) -> bool:
    """
    Applies a custom retention policy to a channel.
    Args:
        channel_id (str): The ID of the channel.
        duration_days (int): Retention duration in days.
    Returns:
        bool: True if successful, False otherwise.
    """
    try:
        logging.info(f"Applying custom retention for '{channel_id}': {duration_days} days.")
        await app.client.admin_conversations_setCustomRetention(
            token=SLACK_USER_TOKEN,
            channel_id=channel_id,
            duration_days=duration_days
        )
        logging.info(f"Custom retention set for channel '{channel_id}' to {duration_days} days successfully.")
        return True
    except SlackApiError as e:
        logging.error(f"Slack API error in apply_custom_retention_policy for '{channel_id}': {e.response['error']}")
        return False
    except Exception as e:
        logging.error(f"Unexpected error in apply_custom_retention_policy for '{channel_id}': {e}")
        return False
    finally:
        await asyncio.sleep(API_CALL_DELAY_SECONDS) # Respect rate limits

async def get_custom_retention(channel_id: str) -> int:
    """
    Retrieves the channel's custom retention policy or workspace default,
    and formats it into a message.
    Args:
        channel_id (str): The ID of the channel.
    Returns:
        str: Formatted retention message, or False on error.
    """
    try:
        logging.info(f"Getting custom retention for '{channel_id}'...")
        response = await app.client.admin_conversations_getCustomRetention(
            token=SLACK_USER_TOKEN,
            channel_id=channel_id
        )
        logging.info(F"Custom retention for channel '{channel_id}': {response}")
        duration_days = int(int(response["duration_days"])/365)
        return duration_days
    except SlackApiError as e:
        logging.error(f"get_custom_retention:\n Slack API error getting retention message for '{channel_id}': {e.response['error']}")
        return None 
    except Exception as e:
        logging.error(f"get_custom_retention:\n Unexpected error getting retention message for '{channel_id}': {e}")
        return None 
    finally:
        await asyncio.sleep(API_CALL_DELAY_SECONDS) # Respect rate limits

async def update_channel_description_with_retention(channel_id: str, retention_message_text: str, current_channel_info: dict) -> bool:
    """
    Appends the channel's description with the retention policy message,
    handling character limits.
    Args:
        channel_id (str): The ID of the channel.
        retention_message_text (str): The retention message to append.
        current_channel_info (dict): Current channel info including purpose.
    Returns:
        bool: True if successful, False otherwise.
    """
    try:
        current_purpose = current_channel_info.get("purpose", {}).get("value", "").strip()
        
        # Construct the message to append
        message_to_append = f"({retention_message_text})"

        ###### Check if only one label is applied 
        label_count = count_data_retention_occurrences(current_purpose)

        if label_count <= 1:
            logging.info(f"Only one or no label found in description for '{channel_id}'. Proceeding to update description if needed.")
            # Ensure the message isn't already present to prevent duplicates
            if message_to_append in current_purpose:
                logging.info(f"Correct retention message already present in description for '{channel_id}'. Skipping update.")
                return True
        else:
            logging.info(f"Multiple labels found in description for '{channel_id}'. Cleaning up before appending new message.")
            logging.info(f"Current description before cleanup: '{current_purpose}'")
            no_labels_purpose = remove_data_retention_substrings(current_purpose)
            logging.info(f"Description after cleanup: '{no_labels_purpose}'")
            current_purpose = no_labels_purpose
        
        # Truncate if necessary
        new_purpose = truncate_description(current_purpose, message_to_append, CHANNEL_DESCRIPTION_MAX_LENGTH)
        
        logging.info(f"Updating description for '{channel_id}' to:\n'{new_purpose}'")
        await app.client.conversations_setPurpose(
            channel=channel_id,
            purpose=new_purpose
        )
        return True
    except SlackApiError as e:
        logging.error(f"Slack API error in update_channel_description_with_retention for '{channel_id}': {e.response['error']}")
        return False
    except Exception as e:
        logging.error(f"Unexpected error in update_channel_description_with_retention for '{channel_id}': {e}")
        return False
    finally:
        await asyncio.sleep(API_CALL_DELAY_SECONDS) # Respect rate limits

async def update_channel_posting_permissions_for_bot(channel_id: int, bot_user_id: int) -> bool:
    """
    Adds the bot's user ID to the channel's posting permissions if a restriction exists.
    Preserves existing allowed users/types.

    Args:
        channel_id (int): The ID of the channel.
        bot_user_id (int): The user ID of the bot to add.
    Returns:
        bool: True if successful or no update needed, False otherwise.  
    """
    try:
        logging.info(f"Checking posting permissions for '{channel_id}' to add bot '{bot_user_id}'.")
        
        # 1. Get current posting preferences
        response = await app.client.admin_conversations_getConversationPrefs(
            token=SLACK_USER_TOKEN,
            channel_id=channel_id
        )
        
        current_prefs = response.get("prefs", {})
        who_can_post_obj = current_prefs.get("who_can_post", {"type": [], "user": []})
        
        current_allowed_users = set(who_can_post_obj.get("user", []))
        current_allowed_types = set(who_can_post_obj.get("type", []))

        # 2. Add bot's user ID if not already present
        if len(current_allowed_users) == 0 and len(current_allowed_types) == 0:
            logging.info(f"No existing posting permissions for '{channel_id}'. We don't have to update posting permissions for '{channel_id}'.")
            return True 
        elif bot_user_id not in current_allowed_users:
            current_allowed_users.add(bot_user_id)
            logging.info(f"Adding bot '{bot_user_id}' to allowed posters list for '{channel_id}'.")
        else:
            logging.info(f"Bot '{bot_user_id}' is already in the allowed posters list for '{channel_id}'. No change needed.")
            return True # Bot is already allowed, so consider this step successful

        # 3. Format the updated user list and types for setConversationPrefs
        formatted_users_string = format_user_ids_for_set_prefs(list(current_allowed_users))
        formatted_types_string_parts = [f"type:{p_type}" for p_type in current_allowed_types]

        # Combine types and users. Slack's API usually expects this as a single string.
        combined_prefs_string = ""
        if formatted_types_string_parts:
            combined_prefs_string += ",".join(formatted_types_string_parts)
        if formatted_users_string:
            if combined_prefs_string:
                combined_prefs_string += ","
            combined_prefs_string += formatted_users_string

        if not combined_prefs_string:
            logging.warning(f"No effective 'who_can_post' preferences to set for '{channel_id}'. Aborting permission update.")
            return False

        prefs_payload = json.dumps({"who_can_post": combined_prefs_string})
        
        # 4. Set the updated posting permissions
        logging.info(f"Setting new posting permissions for '{channel_id}' with payload: {prefs_payload}")
        await app.client.admin_conversations_setConversationPrefs(
            token=SLACK_USER_TOKEN,
            channel_id=channel_id,
            prefs=prefs_payload
        )
        logging.info(f"Posting permissions updated successfully for '{channel_id}'.")
        return True
    except SlackApiError as e:
        logging.error(f"Slack API error in update_channel_posting_permissions_for_bot for '{channel_id}': {e.response['error']}")
        return False
    except Exception as e:
        logging.error(f"Unexpected error in update_channel_posting_permissions_for_bot for '{channel_id}': {e}")
        return False
    finally:
        await asyncio.sleep(API_CALL_DELAY_SECONDS) # Respect rate limits

async def get_channel_id_by_name(channel_name: str) -> str:
    """
    Searches for a channel by name and returns its ID. 
    If multiple channels are found, it logs a warning and returns None.

    Args:
        channel_name (str): The name of the channel to search for.

    Returns:
        str or None: The ID of the unique channel, or None if no channel
                     is found or multiple channels share the same name.
    """
    try:
        response = await app.client.admin_conversations_search(
            token=SLACK_USER_TOKEN,
            query=channel_name.lower(),
            limit=20 # Small limit for efficiency, assuming names are unique
        )
        await asyncio.sleep(API_CALL_DELAY_SECONDS)
        channels = [c for c in response["conversations"] if c["name"] == channel_name]
        if len(channels) == 1:
            logging.info(f"Found unique channel '{channel_name}' with ID: {channels[0]['id']}.")
            return channels[0]["id"]
        elif len(channels) > 1:
            logging.warning(f"Multiple channels found with name '{channel_name}'")
            return None
    except SlackApiError as e:
        logging.error(f"Slack API error during search for '{channel_name}': {e.response['error']}")
        return None
    
async def process_channel(channel_id: str, bot_user_id: str, duration_days: int):
    """
    Processes a single channel: ensures bot membership, applies retention,
    updates description, and adjusts posting permissions.
    Args:
        channel_id (str): The ID of the channel to process.
        bot_user_id (str): The user ID of the bot.
        duration_days (int): Retention duration in days.
    Returns:
        None
    """
    logging.info(f"\n--- Processing Channel: {channel_id} ---")
    is_channel_name=is_valid_channel_id(channel_id)
    if is_channel_name:
        logging.info(f"Looks like a channel_name was provided: {channel_id}")
        get_channel_id = await get_channel_id_by_name(channel_id)
        if get_channel_id==None:
            logging.error(f"Channel ID for channel '{channel_id}' not found. Skipping processing. Will not proceed with DR tasks for channel '{channel_id}' as it is not a valid channel ID.")
            return
        else:
            channel_id = get_channel_id
            logging.info(f"Channel ID for channel '{channel_id}' found. Proceeding with DR tasks for channel '{channel_id}'.")

    # 1. Apply custom retention policy
    await apply_custom_retention_policy(channel_id, duration_days)
    await asyncio.sleep(API_CALL_DELAY_SECONDS)

    # 2. Ensure bot membership and get basic channel info
    bot_added = await add_bot_to_channel(channel_id, bot_user_id)
    if not bot_added:
        logging.error(f"Failed to add bot to channel {channel_id}.")
        logging.warning(f"Bot might already be in channel.")
    channel_info = await get_channel_info(channel_id)
    if not channel_info:
        logging.error(f"Failed to retrieve channel info for {channel_id}.")
        logging.error(f"Skipping channel {channel_id} due to bot membership/info retrieval failure.")
        return
    if channel_info["is_archived"] == True:
        logging.info(f"Channel '{channel_id}' is archived. Skipping channel.")
        return
    await asyncio.sleep(API_CALL_DELAY_SECONDS)

    # 3. Update channel posting permission to add itself
    posting_permission_success = await update_channel_posting_permissions_for_bot(channel_id, bot_user_id)
    if not posting_permission_success:
        logging.warning(f"Failed to update posting permissions for bot in {channel_id}. Bot might not be able to update description.")
    await asyncio.sleep(API_CALL_DELAY_SECONDS+1)

    # 4. Append the channel's description with a message containing the retention policy
    channel_retention_policy = await get_custom_retention(channel_id)
    if not channel_retention_policy:
        logging.error(f"Could not get retention policy for {channel_id}. Skipping description update.")
        return
    retention_message = generate_retention_message(channel_retention_policy)
    await update_channel_description_with_retention(channel_id, retention_message, channel_info)

    logging.info(f"--- Finished Processing Channel: {channel_id} ---")

# --- Main Execution Function ---
async def main():
    logging.info("Starting Slack Channel Automation Script.")
    # Read channel entries (channel_id + retention) from CSV
    channel_entries = await read_channel_ids_from_csv(CSV_FILE_PATH)
    if not channel_entries:
        logging.error("No channel entries found in CSV. Exiting.")
        return
    logging.info(f"Found {len(channel_entries)} channels to process.")

    for i, entry in enumerate(channel_entries):
        cid = entry.get('channel_id')
        duration_days = entry.get('retention_days', DEFAULT_RETENTION_DURATION_DAYS)
        logging.info(f"Processing channel {i+1}/{len(channel_entries)}: {cid} (retention {duration_days} days)")
        await process_channel(cid.strip(), SLACK_BOT_USER_ID, duration_days)
    logging.info("Slack Channel Automation Script finished.")

# Main
# --- Run the Main Function ---
if __name__ == "__main__":
    # Set environment variables before running:
    # export SLACK_BOT_TOKEN='xoxa-E-YOUR_ORG_ADMIN_TOKEN'
    # export SLACK_BOT_USER_ID='A0YOUR_APP_USER_ID'
    # export SLACK_WORKSPACE_ID='T0YOUR_WORKSPACE_ID' # The specific workspace where channels reside

    # Create a dummy CSV for testing if you don't have one
    if not os.path.exists(CSV_FILE_PATH):
        logging.warning(f"CSV file '{CSV_FILE_PATH}' not found. Creating a dummy one for testing.")
        with open(CSV_FILE_PATH, 'w') as f:
            f.write("channel_id,retention\n")
            f.write("C08T5BBGTH8,7\n") # daniel-padilla-1 (7 years)
            f.write("C08T5BCANF4,7\n") # daniel-padilla-2 (7 years)
            f.write("C08TZDGSELQ,3\n") # daniel-padilla-test (7 years)
            f.write("C09A88K3SLC,2\n") # private-channel-retention-test (7 years)
            f.write("C099SC9PEQ7,\n") # public-channel-retention-test (7 years)

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Script interrupted by user.")
    except Exception as e:
        logging.critical(f"Script terminated due to unhandled exception: {e}")