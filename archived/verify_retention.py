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
CSV_INPUT_FILE_PATH = 'channel_ids.csv'
LOG_FILE_PATH = 'slack_channel_automation.log'
CSV_OUTPUT_FILE_PATH = 'channel_retention_report.csv' # The new CSV file where the output will be written
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

# --- Core Task Functions ---

async def get_channel_retention_data(channel_id: str) -> dict:
    """
    Retrieves channel ID, channel name, and current retention policy.
    """
    channel_name = "N/A"
    current_retention_policy = "Not Set"

    try:
        # Get channel name using conversations.info
        info_response = await app.client.conversations_info(
            channel=channel_id,
            token=SLACK_BOT_TOKEN # Use bot token for conversations.info
        )
        
        channel_name = info_response["channel"]["name"]
        logging.info(f"Fetched info for channel {channel_id}: {channel_name}")
            
        # Get custom retention policy using admin.conversations.getCustomRetention
        retention_response = await app.client.admin_conversations_getCustomRetention(
            channel_id=channel_id,
            token=SLACK_USER_TOKEN # Use user token for admin actions
        )
        if retention_response["is_policy_enabled"]:
            current_retention_policy = retention_response["duration_days"]
        logging.info(f"Fetched retention for channel {channel_id}: {current_retention_policy} days")

        channel_retention_data = {
            "channel_id": channel_id,
            "channel_name": channel_name,
            "current_retention_policy": current_retention_policy
        }
        logging.info(f"Compiled retention data for channel {channel_id}: \n {channel_retention_data}")
        return channel_retention_data
    except SlackApiError as e:
        logging.error(f"Slack API error for channel {channel_id}: {e.response['error']}")
    except Exception as e:
        logging.error(f"An unexpected error occurred for channel {channel_id}: {e}")
    finally:
        await asyncio.sleep(API_CALL_DELAY_SECONDS)

async def read_channel_ids_from_csv(file_path: str) -> list:
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

async def write_to_csv(data_list: list, file_path: str, headers: list):
    """Writes a list of dictionaries to a CSV file."""
    try:
        df = pd.DataFrame(data_list)
        df.to_csv(file_path, index=False, columns=headers)
        logging.info(f"Successfully wrote data to '{file_path}'.")
    except Exception as e:
        logging.error(f"Error writing to CSV file '{file_path}': {e}")

# --- Main Execution Function ---
async def main():
    logging.info("Starting Slack Channel Retention Report Script.")
    
    # Read channel IDs from CSV
    channel_ids = await read_channel_ids_from_csv(CSV_INPUT_FILE_PATH)
    if not channel_ids:
        logging.error("No channel IDs found in CSV. Exiting.")
        return
    
    # List to store the results
    retention_report_data = []

    for i, channel_id in enumerate(channel_ids):
        logging.info(f"Processing channel {i+1}/{len(channel_ids)}: {channel_id}")
        data = await get_channel_retention_data(channel_id)
        if data:
            retention_report_data.append(data)
    
    # Define headers for the output CSV
    csv_headers = ["channel_id", "channel_name", "current_retention_policy"]
    
    # Write the collected data to a new CSV file
    await write_to_csv(retention_report_data, CSV_OUTPUT_FILE_PATH, csv_headers)

    logging.info("Slack Channel Retention Report Script finished.")

# --- Run the Main Function ---
if __name__ == "__main__":
    load_dotenv()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Script interrupted by user.")
    except Exception as e:
        logging.critical(f"Script terminated due to unhandled exception: {e}")