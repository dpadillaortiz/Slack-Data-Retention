import os
import logging
import json
import logging
# from datetime import timedelta
import re
import pandas
from pathlib import Path
from email.utils import parsedate_to_datetime

from slack_sdk.web import WebClient
from slack_sdk.errors import SlackApiError

import ssl
import certifi
from dotenv import load_dotenv
load_dotenv()

# Get the path to the certifi CA bundle
ca_file_path = certifi.where()

# Create a custom SSL context
context = ssl.create_default_context(cafile=ca_file_path)

# Disable the strict verification flag
context.verify_flags &= ~ssl.VERIFY_X509_STRICT

# --- Configuration ---
LOG_FILE_PATH = 'slack_channel_automation.log'
CHANNEL_DESCRIPTION_MAX_LENGTH = 250 
RETENTION_MESSAGE_PREFIX = "Data retention : " # Prefix for the message appended to description #(Data retention : ${durationYears} Years)

# --- Slack API Client Initialization ---
SLACK_SIGNING_SECRET = None
SANDBOX_SLACK_BOT_TOKEN = os.getenv("SANDBOX_SLACK_BOT_TOKEN") 
SANDBOX_SLACK_USER_TOKEN = os.getenv("SANDBOX_SLACK_USER_TOKEN")
SANDBOX_SLACK_BOT_USER_ID = os.getenv("SANDBOX_SLACK_BOT_USER_ID")
SANDBOX_SLACK_APP_TOKEN = os.getenv("SANDBOX_SLACK_APP_TOKEN")

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE_PATH),
        logging.StreamHandler() # Also print to console
    ]
)

# Initialize the WebClient with the custom SSL context
# This client will be used by the Bolt app for all API calls.
client = WebClient(
    token=SANDBOX_SLACK_BOT_TOKEN,
    ssl=context
)

class ChannelFilter:
    @staticmethod
    def filter_by_creator(creator_id: str, target_creator_id: str) -> bool:
        """Return whether a channel creator matches the requested creator ID.

        Args:
            creator_id: Creator ID from the channel export row.
            target_creator_id: Creator ID to match against.

        Returns:
            True when creator_id equals target_creator_id, otherwise False.
        """
        return creator_id == target_creator_id
    
    @staticmethod
    def filter_by_name_prefix(channel_name: str, prefix: str) -> bool:
        """Return whether a channel name starts with a prefix.

        Args:
            channel_name: Channel name from the export row.
            prefix: Prefix to compare against.

        Returns:
            True when channel_name starts with prefix (case-insensitive), else False.
        """
        return str(channel_name).lower().startswith(prefix.lower())

class TextUtilities:
    # Regex pattern for matching retention messages in parentheses
    RETENTION_PATTERN = r'\(Data retention.*?\)'
        
    @staticmethod
    def remove_data_retention_substrings(text: str) -> str:
        """Remove existing retention labels from a channel description.

        Args:
            text: Raw channel description text.

        Returns:
            Description text with retention label substrings removed and trimmed.
        """
        cleaned_text = re.sub(TextUtilities.RETENTION_PATTERN, '', text)
        return cleaned_text.strip()
    
    @staticmethod
    def count_data_retention_occurrences(text: str) -> int:
        """Count retention label occurrences in a description string.

        Args:
            text: Description text to inspect.

        Returns:
            Number of retention labels found.
        """
        matches = re.findall(TextUtilities.RETENTION_PATTERN, text)
        return len(matches)
    
    @staticmethod
    def create_description(clean_description_text: str, message_to_append: str) -> str:
        """Build a final channel description that respects Slack length limits.

        Args:
            clean_description_text: Description text with old retention labels removed.
            message_to_append: New retention label to append.

        Returns:
            A description string capped to Slack's 250-character purpose limit.
        """
        max_length = 250
        combined_length = len(clean_description_text) + len(message_to_append) + 2
        if combined_length > max_length:
            # Calculate how much of the original description we can keep
            # Subtract 3 for ellipsis "..."
            space_for_original = max_length - len(message_to_append) - 4
            if space_for_original < 0: # Message to append is already too long
                return message_to_append[:max_length] # Just return truncated message
            
            truncated_original = clean_description_text[:space_for_original]
            return f"{truncated_original}...{message_to_append}"
        else:
            return f"{clean_description_text} {message_to_append}"
        
    @staticmethod
    def format_user_ids_for_set_prefs(user_id_list: list[str]) -> str:
        """Format user IDs into Slack `who_can_post` preference syntax.

        Args:
            user_id_list: User IDs like ["U123", "U456"].

        Returns:
            Comma-separated `user:<id>` string accepted by Slack admin prefs APIs.
        """
        if not user_id_list:
            return ""
        return ",".join([f"user:{uid}" for uid in user_id_list])

class SlackChannel:
    def __init__(self, channel_id: str, client: WebClient = None, retention_years: int = None):
        """Initialize per-channel state used by Slack admin operations.

        Args:
            channel_id: Slack channel ID to operate on.
            client: Slack WebClient instance. Uses shared client if omitted.
            retention_years: Retention duration in years for custom retention API calls.
        """
        self.channel_id = channel_id
        self.retention_years = retention_years
        self.admin_user_token = SANDBOX_SLACK_USER_TOKEN
        self.bot_user_id = SANDBOX_SLACK_BOT_USER_ID
        self.client = client if client else app.client  # Allows testing with mock client

    def add_bot_to_channel(self) -> bool:
        """Invite the configured bot user to the target channel.

        Returns:
            True when the API request succeeds, otherwise False.
        """
        try:
            response = self.client.admin_conversations_invite(
                token=self.admin_user_token, 
                channel_id=self.channel_id,
                user_ids=self.bot_user_id,
            )
            logging.info(f"Bot added to channel {self.channel_id}: {response}")
            return True
        except SlackApiError as e:
            logging.error(f"Error adding bot to channel {self.channel_id}: {e.response['error']}")
            return False
        
    def search_for_channel(self) -> dict | None:
        """Search channel metadata by channel ID using admin APIs.

        Returns:
            Channel dictionary when found, otherwise None.
        """
        try:
            response = self.client.admin_conversations_search(
                token=self.admin_user_token,
                query=self.channel_id
            )
            channels = response['conversations']
            for channel in channels:
                if channel['id'] == self.channel_id:
                    logging.info(f"Channel {self.channel_id} found.")
                    return channel
        except SlackApiError as e:
            logging.error(f"Error searching for channel {self.channel_id}: {e.response['error']}")
            return None

    def get_channel_info(self) -> dict | None:
        """Retrieve channel information from `conversations.info`.

        Returns:
            Channel info dictionary if successful, otherwise None.
        """
        try:
            response = self.client.conversations_info(channel=self.channel_id)
            logging.info(f"Fetched info for channel {self.channel_id}")
            return response['channel']
        except SlackApiError as e:
            logging.error(f"Error fetching info for channel {self.channel_id}: {e.response['error']}")
            return None
        
    def update_retention_policy(self) -> bool:
        """Apply a custom retention policy for the channel.

        Uses `retention_years` converted to days (`years * 365`).

        Returns:
            True on successful update, otherwise False.
        """
        if self.retention_years is None:
            logging.error(f"Retention years not set for channel {self.channel_id}")
            return False
        try:
            duration_days = self.retention_years * 365
            response = self.client.admin_conversations_setCustomRetention(
                token=self.admin_user_token,
                channel_id=self.channel_id,
                duration_days=duration_days
            )
            logging.info(f"Updated retention policy for channel {self.channel_id}: {response}")
            return True
        except SlackApiError as e:
            logging.error(f"Error updating retention policy for channel {self.channel_id}: {e.response['error']}")
            return False

    def get_retention_policy(self) -> dict | None:
        """Fetch the current custom retention configuration for the channel.

        Returns:
            API response dictionary when successful, otherwise None.
        """
        try:
            response = self.client.admin_conversations_getCustomRetention(
                token=self.admin_user_token,
                channel_id=self.channel_id
            )
            logging.info(f"Fetched retention policy for channel {self.channel_id}: {response}")
            return response
        except SlackApiError as e:
            logging.error(f"Error fetching retention policy for channel {self.channel_id}: {e.response['error']}")
            return None
        
    def update_channel_description(self, new_description: str) -> bool:
        """Update the channel purpose/description text.

        Args:
            new_description: New purpose text to write to the channel.

        Returns:
            True when the update succeeds, otherwise False.
        """
        try:
            response = self.client.conversations_setPurpose(
                channel=self.channel_id,
                purpose=new_description
            )
            logging.info(f"Updated description for channel {self.channel_id}: {response}")
            return True
        except SlackApiError as e:
            logging.error(f"Error updating description for channel {self.channel_id}: {e.response['error']}")
            return False

    def get_posting_permissions(self) -> dict | None:
        """Read channel posting restrictions from admin conversation preferences.

        Returns:
            The `prefs` dictionary on success, otherwise None.
        """
        try:
            response = self.client.admin_conversations_getConversationPrefs(
                token=self.admin_user_token,
                channel_id=self.channel_id
            )
            logging.info(f"Fetched posting permissions for channel {self.channel_id}: {response}")
            return response.get("prefs")
        except SlackApiError as e:
            logging.error(f"Error fetching posting permissions for channel {self.channel_id}: {e.response['error']}")
            return None
    
    def update_posting_permissions(self, prefs_payload: str) -> bool:
        """Write updated posting permission preferences for the channel.

        Args:
            prefs_payload: JSON string payload accepted by Slack admin prefs API.

        Returns:
            True when update succeeds, otherwise False.
        """
        try:
            response = self.client.admin_conversations_setConversationPrefs(
                token=self.admin_user_token,
                channel_id=self.channel_id,
                prefs=prefs_payload
            )
            logging.info(f"Updated posting permissions for channel {self.channel_id}: {response}")
            return True
        except SlackApiError as e:
            logging.error(f"Error updating posting permissions for channel {self.channel_id}: {e.response['error']}")
            return False

class PostingPermissionsManager:
    def __init__(self, bot_user_id: str):
        """Store bot user ID used when patching posting permissions.

        Args:
            bot_user_id: Bot user ID to ensure is included in allowed posters.
        """
        self.bot_user_id = bot_user_id
    
    def apply_posting_permissions(self, conversation: SlackChannel) -> bool:
        """Ensure the bot can post in restricted channels before updates.

        Args:
            conversation: Channel wrapper used to read/write posting preferences.

        Returns:
            True when no change is needed or update succeeds, otherwise False.
        """
        try: 
            # All the posting permission logic
            # 1. Get current posting preferences
            current_permissions = conversation.get_posting_permissions()
            if not current_permissions:
                logging.error(f"Failed to get posting permissions")
                return False
            who_can_post_obj = current_permissions.get("who_can_post", {"type": [], "user": []})
            current_allowed_users = set(who_can_post_obj.get("user", []))
            current_allowed_types = set(who_can_post_obj.get("type", []))

            # 2. Add bot's user ID if not already present
            if len(current_allowed_users) == 0 and len(current_allowed_types) == 0:
                logging.info(f"No existing posting permissions for '{conversation.channel_id}'. We don't have to update posting permissions for '{conversation.channel_id}'.")
                return True 
            elif self.bot_user_id not in current_allowed_users:
                current_allowed_users.add(self.bot_user_id)
                logging.info(f"Adding bot '{self.bot_user_id}' to allowed posters list for '{conversation.channel_id}'.")
            else:
                logging.info(f"Bot '{self.bot_user_id}' is already in the allowed posters list for '{conversation.channel_id}'. No change needed.")
                return True 
            
            # 3. Format the updated user list and types for setConversationPrefs
            formatted_users_string = TextUtilities.format_user_ids_for_set_prefs(list(current_allowed_users))
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
                logging.warning(f"No effective 'who_can_post' preferences to set for '{conversation.channel_id}'. Aborting permission update.")
                return False

            prefs_payload = json.dumps({"who_can_post": combined_prefs_string})

            # 4. Set the updated posting permissions
            logging.info(f"Setting new posting permissions for '{conversation.channel_id}' with payload: {prefs_payload}")
            if not conversation.update_posting_permissions(prefs_payload):
                return False  # ← Use existing method
            logging.info(f"Posting permissions updated successfully for '{conversation.channel_id}'.")
            return True
        except Exception as e:
            logging.error(f"Unexpected error in apply_posting_permissions for '{conversation.channel_id}': {e}")
            return False



class DescriptionManager:
    """Handles channel description formatting and updates to reflect retention policies."""
    def update_with_retention(self, conversation: SlackChannel) -> bool:
        """Synchronize channel description with the expected retention label.

        Args:
            conversation: Channel wrapper containing ID and retention year context.

        Returns:
            True when description is already correct or successfully updated, else False.
        """
        if conversation.retention_years is None:
            logging.error(f"Retention years not set for channel {conversation.channel_id}")
            return False
        retention_label = f"({RETENTION_MESSAGE_PREFIX}{conversation.retention_years} Years)"

        # All the description formatting/updating logic
        try:
            channel_info = conversation.get_channel_info()
            if channel_info is None:
                logging.error(f"Failed to get channel info for '{conversation.channel_id}'")
                return False
            current_description = channel_info.get("purpose", {}).get("value", None)

            if current_description is None:
                logging.info(f"No description found for channel '{conversation.channel_id}'. Adding retention info.")
                return conversation.update_channel_description(retention_label)
            elif TextUtilities.count_data_retention_occurrences(current_description) == 1 and (retention_label in current_description):
                logging.info(f"Retention label is already correct for channel '{conversation.channel_id}'. No update needed.")
                return True  # No update needed
            
            logging.info(f"Current description for channel '{conversation.channel_id}': '{current_description}'")

            # 1. Clean existing retention labels
            clean_description = TextUtilities.remove_data_retention_substrings(current_description)
            logging.info(f"Cleaned description for channel '{conversation.channel_id}': '{clean_description}'")

            # 2. Create new retention message
            logging.info(f"Retention message to append for channel '{conversation.channel_id}': '{retention_label}'")

            # 3. Create updated description
            updated_description = TextUtilities.create_description(
                clean_description_text=clean_description,
                message_to_append=retention_label
            )
            logging.info(f"Updated description for channel '{conversation.channel_id}': '{updated_description}'")

            # 4. Update the channel description via Slack API
            return conversation.update_channel_description(updated_description)
        except Exception as e:
            logging.error(f"Unexpected error in update_with_retention for '{conversation.channel_id}': {e}")
            return False

class ChannelWorkflow:
    def __init__(self, bot_user_id: str = SANDBOX_SLACK_BOT_USER_ID, client: WebClient = None):
        """Create workflow dependencies for per-channel processing.

        Args:
            bot_user_id: Bot user ID used by permission manager.
            client: Slack WebClient instance. Shared client is used when omitted.
        """
        self.bot_user_id = bot_user_id
        self.client = client if client else app.client
        self.permissions_manager = PostingPermissionsManager(bot_user_id)
        self.description_manager = DescriptionManager()
    
    def process_channel(self, channel_id: str, retention_years: int) -> bool:
        """Run the end-to-end retention + description workflow for one channel.

        Args:
            channel_id: Slack channel ID to process.
            retention_years: Retention duration in years.

        Returns:
            True when workflow completes successfully, otherwise False.
        """
        logging.info(f"\n--- Processing Channel: {channel_id} ---")
        
        conversation = SlackChannel(channel_id, client = self.client, retention_years = retention_years)
        
        # Phase 1: Apply retention policy
        if not conversation.update_retention_policy():
            logging.error(f"Failed to apply retention policy for {channel_id}")
            return False
        
        # Phase 2: Update description workflow
        success = self._update_description_workflow(conversation)
        
        logging.info(f"--- Finished Processing Channel: {channel_id} ---")
        return success
    
    def _update_description_workflow(self, conversation: SlackChannel) -> bool:
        """Execute description-related steps after retention is applied.

        This helper checks archived status, tries bot invite and permission updates,
        then applies the retention label to the channel description.

        Args:
            conversation: Channel wrapper used for API operations.

        Returns:
            True when description stage succeeds, otherwise False.
        """
        channel_id = conversation.channel_id
        
        # Step 0: Check if archived
        channel = conversation.search_for_channel()
        if not channel:
            logging.error(f"Failed to find channel {channel_id}")
            return False
        if channel.get("is_archived", False):
            logging.warning(f"Channel {channel_id} is archived. Skipping description update.")
            return False 
        
        # Step 1: Add bot (non-blocking)
        if not conversation.add_bot_to_channel():
            logging.warning(f"Failed to add bot to channel {channel_id}. Bot may already be in channel.")
        
        # Step 2: Update permissions (non-blocking)
        if not self.permissions_manager.apply_posting_permissions(conversation):
            logging.warning(f"Failed to update posting permissions for {channel_id}. Continuing anyway.")
        
        # Step 3: Update description
        if not self.description_manager.update_with_retention(conversation):
            logging.error(f"Failed to update description for {channel_id}")
            return False

        if get_retention_policy := conversation.get_retention_policy():
            logging.info(f"Retention policy for {channel_id}: {get_retention_policy}")
        
        return True
    
class CSVProcessor:
    def __init__(self, file_path: str):
        """Initialize a CSV processor for a specific file.

        Args:
            file_path: Path to the CSV file to read from.
        """
        self.file_path = file_path
    
    def read_csv_data(self):
        """Read all rows from CSV into a list of dictionaries.

        Returns:
            List of row dictionaries.
        """
        df = pandas.read_csv(self.file_path)
        return df.to_dict(orient='records')
    
    def filter_relavent_columns(self, *columns):
        """Read and validate only the requested columns from CSV.

        Args:
            *columns: Column names required in the output rows.

        Returns:
            List of dictionaries containing only requested columns.

        Raises:
            ValueError: If any requested column is missing from the CSV file.
        """
        df = pandas.read_csv(self.file_path, usecols=columns)
        required_columns = {*columns}
        if not required_columns.issubset(set(df.columns)):
            missing = required_columns - set(df.columns)
            logging.error(f"Missing required columns in CSV: {missing}")
            raise ValueError(f"Missing required columns in CSV: {missing}")
        return df.to_dict(orient='records')
    
    def write_csv_data(self, data: list[dict], output_file_path: str):
        """Write rows to CSV, appending when output already exists.

        Args:
            data: Row dictionaries to persist.
            output_file_path: Destination CSV path.
        """
        output_path_exists = os.path.exists(output_file_path)
        df = pandas.DataFrame(data)
        # Convert Private column to integer to avoid writing as float (1.0)
        if "Private" in df.columns:
            df["Private"] = df["Private"].astype(int)
        if "Archived" in df.columns:
            if df["Archived"].dtype == None:
                df["Archived"] = 0
            df["Archived"] = df["Archived"].astype(int)
        df.to_csv(output_file_path, 
                  mode='a' if output_path_exists else 'w',
                  header = not output_path_exists,
                  index=False)
        
def apply_data_retention_workflow_to_channels(csv_from_processor: list[dict], retention_years: int, client: WebClient):
    """Apply the channel workflow to each row in a channel list.

    Args:
        csv_from_processor: Channel dictionaries expected to include an `ID` key.
        retention_years: Retention duration in years.
        client: Slack WebClient used for API calls.
    """
    workflow = ChannelWorkflow(bot_user_id=SANDBOX_SLACK_BOT_USER_ID, client=client)
    for channel in csv_from_processor:
        channel_id = channel["ID"]
        workflow.process_channel(channel_id, retention_years)

def process_secinc_channels(channel_export_directory: str, output_file: str) -> list[dict]:
    """Filter SECINC/FIREFIGHTER channels from export CSV files.

    Applies naming, creator, and year filters, normalizes date formatting, and
    writes cumulative filtered rows to the output file.

    Args:
        channel_export_directory: Folder containing exported channel CSV files.
        output_file: Path to write filtered rows.

    Returns:
        List of filtered channel dictionaries.
    """
    directory = Path(channel_export_directory)
    # Define target columns to extract
    target_columns = ["Name", "ID", "Private", "Archived", "Creator ID", "Creation date"]
    # Define filter functions
    firefighter_id = "U01JHNPKQ4A"
    secinc_filter = lambda channel_name, channel_creator_id: ChannelFilter.filter_by_name_prefix(channel_name, "secinc-") or ChannelFilter.filter_by_creator(channel_creator_id, firefighter_id)
    year_filter = lambda desired_year, creation_date: desired_year in creation_date
    filtered_channels = []

    # Process each CSV file in the directory
    for csv_file in directory.glob('*.csv'):
        logging.info(f"Processing file: {csv_file}")
        file = CSVProcessor(csv_file)
        filtered_data = file.filter_relavent_columns(*target_columns)
        # Apply filters and format dates
        for entry in filtered_data:
            if secinc_filter(entry["Name"], entry["Creator ID"]) and year_filter("2025", entry["Creation date"]):
                entry_date = parsedate_to_datetime(entry["Creation date"])
                entry["Creation date"] = entry_date.strftime("%Y-%m-%d %H:%M:%S")
                logging.info(f"Filtered Entry: {entry}")
                filtered_channels.append(entry)
        # Write filtered data to a new CSV
        file.write_csv_data(filtered_channels, output_file)
    return filtered_channels
    
def main():
    """Run the batch channel retention automation pipeline.

    Workflow:
        1. Filter channels from export CSV files.
        2. Log the total number of matched channels.
        3. Apply retention and description updates to each matched channel.
    """
    logging.info("Starting Slack Channel Automation Script")

    '''
    Alternatively, if you want to skip the CSV processing step and directly input channel IDs for the workflow, you can do so by creating a list of channel ID dicts like this: 
    ```
    channels = [
        {"ID": "C12345678"},
        {"ID": "C23456789"},
        # Add more channel IDs as needed
    ]
    ```

    Additionally, if you'd like to apply data retention directly from a CSV without filtering, you can do the following:
    ```
    file = CSVProcessor("your_channel_file.csv")
    file_to_dict = file.read_csv_data()
    apply_data_retention_workflow_to_channels(file_to_dict, retention_years=10, client=client)
    ```
    '''
    
    secinc_channels = process_secinc_channels("channel_export", "filtered_channels.csv")
    logging.info(f"Total filtered channels: {len(secinc_channels)}")
    
    apply_data_retention_workflow_to_channels(secinc_channels, retention_years=10, client=client)


if __name__ == "__main__":
    main()

 

    

        