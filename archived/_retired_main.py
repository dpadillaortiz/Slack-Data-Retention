'''
Keeping this file for reference, but all logic has been moved to apply_description.py, now renamed as main.py

This scripted was used in August slack retention project, but is now retired.
'''



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
DEFAULT_RETENTION_DURATION_DAYS = 2555 # (730 = 2 years)(2555 = 7 years) Example default if channel has no custom policy
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
def remove_data_retention_substrings(text: str) -> str:
    """
    Removes all occurrences of the patterns "(Data retention : x Years)"
    and "(Data retention : Error retrieving policy.)" from a string.

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
    pattern = r'\(Data retention.*?\)|\(Data retention : \s*\d+\s*Years\)|\(Data retention : Error retrieving policy\.\)'
    
    # re.sub() finds all non-overlapping occurrences of the pattern in the text
    # and replaces them with an empty string ('').
    cleaned_text = re.sub(pattern, '', text)
    
    # After removing the patterns, we'll strip any leading/trailing whitespace
    # that might be left over from the replacements.
    return cleaned_text.strip()

def count_data_retention_occurrences(text: str) -> int:
    """
    Counts all occurrences of the patterns "(Data retention : x Years)"
    and "(Data retention : Error retrieving policy.)" from a string.

    Args:
        text: The input string to be searched.

    Returns:
        The number of times the pattern was found.
    """
    # The same regex pattern is used to find the occurrences.
    pattern = r'\(Data retention.*?\)|\(Data retention : \s*\d+\s*Years\)|\(Data retention : Error retrieving policy\.\)'
    
    # re.findall() returns a list of all non-overlapping matches.
    # The length of this list is the number of occurrences.
    matches = re.findall(pattern, text)
    
    return len(matches)

def has_hyphen_and_underscore(input_string: str) -> bool:
    """
    Checks if a string contains both a hyphen ('-') and an underscore ('_').

    Args:
        input_string: The string to check.

    Returns:
        True if the string contains both characters, False otherwise.
    """
    return '-' in input_string or '_' in input_string

def format_user_ids_for_set_prefs(user_id_list):
    """
    Converts a list of user IDs (e.g., ['U1234', 'U5678'])
    into the format required by admin.conversations.setConversationPrefs
    (e.g., 'user:U1234,user:U5678').
    """
    if not user_id_list:
        return ""
    return ",".join([f"user:{uid}" for uid in user_id_list])

def truncate_description(description_text, message_to_append, max_length):
    """
    Appends a message to a description, truncating if necessary to stay within max_length.
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

# --- Core Task Functions ---
async def read_channel_ids_from_csv(file_path):
    """Reads channel IDs from a specified CSV file."""
    try:
        df = pd.read_csv(file_path)
        if 'channel_id' not in df.columns:
            logging.error(f"CSV file '{file_path}' must contain a 'channel_id' column.")
            return []
        channel_ids = df['channel_id'].dropna().astype(str).tolist()
        logging.info(f"Successfully read {len(channel_ids)} channel IDs from '{file_path}'.")
        return list(set(channel_ids)) # Return unique channel IDs
    except FileNotFoundError:
        logging.error(f"CSV file not found at '{file_path}'.")
        return []
    except Exception as e:
        logging.error(f"Error reading CSV file '{file_path}': {e}")
        return []

async def get_bot_membership_status(channel_id):
    try:
        response = await app.client.admin_conversations_invite(
            token=SLACK_USER_TOKEN, # Use user token for admin actions
            channel_id=channel_id,
            user_ids=SLACK_BOT_USER_ID,
        )
        if response["ok"]:
            logging.info(f"Bot invited to channel '{channel_id}' successfully.")
            return True 
        else:
            logging.error(f"Failed to invite bot to channel '{channel_id}': {response['error']}")
            return False # Cannot proceed if bot can't join
    except SlackApiError as e:
        logging.warning(f"Slack API error getting channel info for '{channel_id}': {e.response['error']}")
        logging.warning(f"Enterprise Data Retention bot may already be a member of the channel '{channel_id}'.")
        return False
    except Exception as e:
        logging.error(f"Unexpected error in get_bot_membership_status for '{channel_id}': {e}")
        return False
    finally:
        await asyncio.sleep(API_CALL_DELAY_SECONDS) # Respect rate limits

async def get_channel_info(channel_id):
    """
    Checks if the bot is a member of the channel.
    Returns True if the bot is a member, False otherwise.
    """
    try:
        response = await app.client.conversations_info(channel=channel_id)
        logging.info(f"Bot successfully read channel '{channel_id}'.")
        channel_info = response["channel"]
        channel_info["is_member"] = True 
        return channel_info
    except SlackApiError as e:
        logging.error(f"Slack API error getting channel info for '{channel_id}': {e.response['error']}")
        return None
    except Exception as e:
        logging.error(f"Unexpected error in get_bot_membership_status for '{channel_id}': {e}")
        return None
    finally:
        await asyncio.sleep(API_CALL_DELAY_SECONDS) # Respect rate limits

async def ensure_bot_membership_and_get_info(channel_id, bot_user_id):
    """
    Ensures the bot is a member of the channel and retrieves basic channel info.
    Invites the bot if it's not a member.
    """
    channel_info = await get_channel_info(channel_id)
    bot_membership_status = await get_bot_membership_status(channel_id)
    logging.info(f"channel_info: '{channel_info}'...")
    try:
        if channel_info is not None and bot_membership_status:
            logging.info(f"Bot is already a member of channel '{channel_id}'.")
            return channel_info
        elif channel_info is None and not bot_membership_status:
            logging.info(f"Bot not in channel '{channel_id}'. Attempting to invite bot...")
            invite_response = await app.client.admin_conversations_invite(
                token=SLACK_USER_TOKEN, # Use user token for admin actions
                channel_id=channel_id,
                user_ids=bot_user_id,
            )
            if invite_response["ok"]:
                logging.info(f"Bot invited to channel '{channel_id}' successfully.")
                channel_info = await get_channel_info(channel_id)
                channel_info["is_member"] = True
                logging.info(f"refetching channel_info: '{channel_info}'...")
                return channel_info
            else:
                logging.error(f"Failed to invite bot to channel '{channel_id}': {invite_response['error']}")
                return None # Cannot proceed if bot can't join
        else:
            logging.info(f"Bot returned channel info for '{channel_id}'")
            logging.info(f"channel_info: '{type(channel_info)}'...")
            return channel_info
    except SlackApiError as e:
        logging.error(f"Slack API error in ensure_bot_membership_and_get_info for '{channel_id}': {e.response['error']}")
        return None # Cannot proceed if bot can't join
    except Exception as e:
        logging.error(f"Unexpected error in ensure_bot_membership_and_get_info for '{channel_id}': {e}")
        return None
    finally:
        await asyncio.sleep(API_CALL_DELAY_SECONDS) # Respect rate limits

async def apply_custom_retention_policy(channel_id, duration_days):
    """Applies a custom retention policy to a channel."""
    try:
        logging.info(f"Applying custom retention for '{channel_id}': {duration_days} days.")
        response = await app.client.admin_conversations_setCustomRetention(
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

async def get_channel_retention_message(channel_id):
    """
    Retrieves the channel's custom retention policy or workspace default,
    and formats it into a message.
    """
    try:
        # Try to get custom retention first
        response = await app.client.admin_conversations_getCustomRetention(
            token=SLACK_USER_TOKEN,
            channel_id=channel_id
        )
        logging.info(response)
        if response["ok"]:
            duration_days = int(int(response["duration_days"])/365)
            if duration_days is not None:
                logging.info(f"Channel '{channel_id}' has custom retention: {duration_days} Years.")
                return f"{RETENTION_MESSAGE_PREFIX}{duration_days} Years"
        
        # If no custom retention or not enabled, get workspace default
        logging.info(f"Channel '{channel_id}' has no custom retention, using organization default.")
        return f"{RETENTION_MESSAGE_PREFIX}2 Years."
    except SlackApiError as e:
        logging.error(f"Slack API error getting retention message for '{channel_id}': {e.response['error']}")
        return False #f"{RETENTION_MESSAGE_PREFIX}Error retrieving policy."
    except Exception as e:
        logging.error(f"Unexpected error getting retention message for '{channel_id}': {e}")
        return False #f"{RETENTION_MESSAGE_PREFIX}Error retrieving policy."
    finally:
        await asyncio.sleep(API_CALL_DELAY_SECONDS) # Respect rate limits

async def update_channel_description_with_retention(channel_id, retention_message_text, current_channel_info):
    """
    Appends the channel's description with the retention policy message,
    handling character limits.
    """
    try:
        current_purpose = current_channel_info.get("purpose", {}).get("value", "").strip()
        
        # Construct the message to append
        message_to_append = f"({retention_message_text})"

        ###### Check if only one label is applied 
        label_count = count_data_retention_occurrences(current_purpose)

        if label_count == 1 or label_count == 0:
            logging.info(f"Only one or no label found in description for '{channel_id}'. Proceeding to update description.")
            # Ensure the message isn't already present to prevent duplicates
            if message_to_append in current_purpose:
                logging.info(f"Retention message already present in description for '{channel_id}'. Skipping update.")
                return True
        else:
            logging.info(f"Multiple labels found in description for '{channel_id}'. Cleaning up before appending new message.")
            # added by gemini
            # Clean up existing labels before appending the new one
            # current_purpose = remove_data_retention_substrings(current_purpose)
        
        """
        # -------------Turning of for now
        # Ensure the message isn't already present to prevent duplicates
        if message_to_append in current_purpose:
            logging.info(f"Retention message already present in description for '{channel_id}'. Skipping update.")
            return True
        """
        
        # Truncate if necessary
        new_purpose = truncate_description(current_purpose, message_to_append, CHANNEL_DESCRIPTION_MAX_LENGTH)
        
        logging.info(f"Updating description for '{channel_id}' to: '{new_purpose}'")
        response = await app.client.conversations_setPurpose(
            channel=channel_id,
            purpose=new_purpose
        )
        if response["ok"]:
            logging.info(f"Channel description for '{channel_id}' updated successfully.")
            return True
        else:
            logging.error(f"Failed to update description for '{channel_id}': {response['error']}")
            return False
    except SlackApiError as e:
        logging.error(f"Slack API error in update_channel_description_with_retention for '{channel_id}': {e.response['error']}")
        return False
    except Exception as e:
        logging.error(f"Unexpected error in update_channel_description_with_retention for '{channel_id}': {e}")
        return False
    finally:
        await asyncio.sleep(API_CALL_DELAY_SECONDS) # Respect rate limits

async def update_channel_posting_permissions_for_bot(channel_id, bot_user_id):
    """
    Adds the bot's user ID to the channel's posting permissions if a restriction exists.
    Preserves existing allowed users/types.
    """
    try:
        logging.info(f"Checking posting permissions for '{channel_id}' to add bot '{bot_user_id}'.")
        
        # 1. Get current posting preferences
        response = await app.client.admin_conversations_getConversationPrefs(
            token=SLACK_USER_TOKEN,
            channel_id=channel_id
        )
        if not response["ok"]:
            logging.error(f"Failed to get current posting prefs for '{channel_id}': {response['error']}")
            return False
        
        current_prefs = response.get("prefs", {})
        who_can_post_obj = current_prefs.get("who_can_post", {"type": [], "user": []})
        
        current_allowed_users = set(who_can_post_obj.get("user", []))
        current_allowed_types = set(who_can_post_obj.get("type", []))

        # 2. Add bot's user ID if not already present
        if len(current_allowed_users) == 0 and len(current_allowed_types) == 0:
            logging.info(f"No existing posting permissions for '{channel_id}'. We don't have to update posting permissions for '{channel_id}'.")
            return True # No existing permissions, nothing to update
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
        set_response = await app.client.admin_conversations_setConversationPrefs(
            token=SLACK_USER_TOKEN,
            channel_id=channel_id,
            prefs=prefs_payload
        )
        
        if set_response["ok"]:
            logging.info(f"Successfully updated posting permissions for channel '{channel_id}'.")
            return True
        else:
            logging.error(f"Failed to set posting permissions for '{channel_id}': {set_response['error']}")
            return False
            
    except SlackApiError as e:
        logging.error(f"Slack API error in update_channel_posting_permissions_for_bot for '{channel_id}': {e.response['error']}")
        return False
    except Exception as e:
        logging.error(f"Unexpected error in update_channel_posting_permissions_for_bot for '{channel_id}': {e}")
        return False
    finally:
        await asyncio.sleep(API_CALL_DELAY_SECONDS) # Respect rate limits

async def get_channel_id_by_name(channel_name: str):
    """
    Searches for a channel by name and returns its ID. If multiple
    channels are found, it logs a warning and returns None.

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
    
async def check_channel_retention_policy(channel_id: str, desired_retention_days: int) -> bool:
    """
    Checks if a channel's custom retention policy is equal to the desired retention.

    This function leverages the admin.conversations.getCustomRetention API method,
    which is part of the Slack Admin API and requires an organization-level token.

    Args:
        channel_id (str): The ID of the channel to check.
        desired_retention_days (int): The retention duration in days to check against.

    Returns:
        bool: True if the channel's custom retention policy matches the desired
              rate, False otherwise or if an error occurs.
    """
    try:
        # Use admin.conversations.getCustomRetention to check the policy
        response = await app.client.admin_conversations_getCustomRetention(
            channel_id=channel_id,
            token=SLACK_USER_TOKEN  # Use the user token for admin actions
        )
        
        # The 'duration_days' field will exist if a custom policy is set
        current_retention_days = response["duration_days"]

        if current_retention_days is not None:
            # The API returns an integer for the duration
            if current_retention_days == desired_retention_days:
                logging.info(f"✅ Channel {channel_id} matches the desired retention of {desired_retention_days} days.")
                return True
            else:
                logging.warning(f"❌ Channel {channel_id} has retention of {current_retention_days} days, not {desired_retention_days}.")
                return False
        else:
            logging.info(f"Channel {channel_id} has no custom retention policy set.")
            return False

    except SlackApiError as e:
        print(f"Slack API error: {e.response['error']}")
        return False
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return False
    
async def process_channel(channel_id, bot_user_id, channels_to_exclude, apply_custom_retention):
    """
    Processes a single channel: ensures bot membership, applies retention,
    updates description, and adjusts posting permissions.
    """
    logging.info(f"\n--- Processing Channel: {channel_id} ---")
    # Pre-check if only channel_name is provided
    if channel_id in channels_to_exclude:
        logging.info(f"Skipping channel '{channel_id}' as it is in the check_against list.")
        return
    is_channel_name=has_hyphen_and_underscore(channel_id)
    if is_channel_name == True:
        logging.info(f"Looks like a channel_name was provided: {channel_id}")
        get_channel_id = await get_channel_id_by_name(channel_id)
        if get_channel_id==None:
            logging.error(f"Channel ID for channel '{channel_id}' not found. Skipping processing. Will not proceed with DR tasks for channel '{channel_id}' as it is not a valid channel ID.")
            return
        else:
            channel_id = get_channel_id
            logging.info(f"Channel ID for channel '{channel_id}' found. Proceeding with DR tasks for channel '{channel_id}'.")
    if apply_custom_retention == True:
        # Check if channel has correct retention policy
        retention_check_success = await check_channel_retention_policy(channel_id, DEFAULT_RETENTION_DURATION_DAYS)
        if not retention_check_success:
            logging.info(f"Channel {channel_id} does not have the desired retention policy. Proceeding with other tasks.")
        
            # 1. Apply custom retention first to avoid errors with archived channels 
            # # # ALWAYS CHECK THE SET DEFAULT_RETENTION_DURATION_DAYS
            # You might want to get this duration from your CSV or another source
            desired_retention_days = DEFAULT_RETENTION_DURATION_DAYS
            retention_applied_success = await apply_custom_retention_policy(channel_id, desired_retention_days)
            if not retention_applied_success:
                logging.warning(f"Failed to apply custom retention for {channel_id}. Proceeding with other tasks.")
    
    await asyncio.sleep(API_CALL_DELAY_SECONDS)
    # 2. Ensure bot membership and get basic channel info
    channel_info = await ensure_bot_membership_and_get_info(channel_id, bot_user_id)
    #json_channel_info = json.loads(channel_info)
    if not channel_info:
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
    
    await asyncio.sleep(3)
    # 4. Append the channel's description with a message containing the retention policy
    retention_message = await get_channel_retention_message(channel_id)
    if retention_message:
        await update_channel_description_with_retention(channel_id, retention_message, channel_info)
    else:
        logging.warning(f"Could not get retention message for {channel_id}. Skipping description update.")

    logging.info(f"--- Finished Processing Channel: {channel_id} ---")






# --- Main Execution Function ---
async def main():
    enable_data_retention = input(f"Do you want to apply data retention policy to all channels? (yes/no): ").strip().lower()
    if enable_data_retention in ['yes', 'y']:
        apply_custom_retention = True
        user_input = input(f"The rentation policy will be set to {DEFAULT_RETENTION_DURATION_DAYS} days. Do you want to proceed? (yes/no): ").strip().lower()
        if user_input not in ['yes', 'y']:
            logging.info("User chose not to proceed with the retention policy update. Exiting script.")
            return
    else:
        are_you_ready = input("Are you ready to update channel descriptions without applying data retention policy? (yes/no): ").strip().lower()
        if are_you_ready not in ['yes', 'y']:
            logging.info("User chose not to proceed with updating channel descriptions. Exiting script.")
            return
        apply_custom_retention = False
        logging.info("User chose not to apply data retention policy. Only updating channel descriptions.")
    
    
    
    logging.info("Starting Slack Channel Automation Script.")
    # Read channel ID from exlcusion list
    channels_to_exclude = await read_channel_ids_from_csv("exclude_channels.csv")
    if not channels_to_exclude:
        logging.error("No channel IDs found in CSV. Exiting.")
        return
    logging.info(f"Found {len(channels_to_exclude)} channels to process.")

    # Read channel IDs from CSV
    channel_ids = await read_channel_ids_from_csv(CSV_FILE_PATH)
    if not channel_ids:
        logging.error("No channel IDs found in CSV. Exiting.")
        return
    logging.info(f"Found {len(channel_ids)} channels to process.")

    for i, channel_id in enumerate(channel_ids):
        logging.info(f"Processing channel {i+1}/{len(channel_ids)}: {channel_id}")
        await process_channel(channel_id.strip(), SLACK_BOT_USER_ID, channels_to_exclude, apply_custom_retention=apply_custom_retention)
    logging.info("Slack Channel Automation Script finished.")

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
            f.write("channel_id\n")
            f.write("C08T5BBGTH8\n") # daniel-padilla-1
            f.write("C08T5BCANF4\n") # daniel-padilla-2
            f.write("C08TZDGSELQ\n") # daniel-padilla-test
            f.write("C09A88K3SLC\n") # private-channel-retention-test
            f.write("C099SC9PEQ7\n") # public-channel-retention-test

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Script interrupted by user.")
    except Exception as e:
        logging.critical(f"Script terminated due to unhandled exception: {e}")