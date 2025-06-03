require('dotenv').config();
const { App } = require('@slack/bolt');
const fs = require('fs');
const csv = require('csv-parser');
const { Parser } = require('json2csv');

// --- Configuration ---
// Slack token
const token = process.env.APPLY_BOT_TOKEN;
const slackSigningSecret = process.env.APPLY_SIGNING_SECRET;
const slackUserToken = process.env.APPLY_USER_TOKEN;
// CSVs
const csvFilePath = process.env.CSV_FILE_PATH;
const csvSuccessPath = 'logs/log_successful_channels.csv'; // New path for successful channels
const csvFailedPath = 'logs/log_failed_channels.csv';     // New path for failed channels
// Constant variables
const retentionDays = parseInt(process.env.RETENTION_DAYS, 10);
// Adjust this if your CSV header for channel IDs is different (case-insensitive check is done below)
const csvChannelIdHeader = 'channel_id';
// Optional delay between API calls (in milliseconds) to help avoid rate limits
const apiCallDelay = 3000; // 300ms

// --- Validate Configuration ---
if (!token) {
    console.error('Error: SLACK_BOT_TOKEN environment variable is required. Please set it in the .env file.');
    process.exit(1); // Exit script
}
if (isNaN(retentionDays) || retentionDays <= 0) {
    console.error(`Error: Invalid RETENTION_DAYS value (${process.env.RETENTION_DAYS}). It must be a positive number.`);
    process.exit(1);
}
if (!fs.existsSync(csvFilePath)) {
    console.error(`Error: CSV file not found at path: ${csvFilePath}`);
    console.error('Please ensure the file exists or set the correct CSV_FILE_PATH in the .env file.');
    process.exit(1);
}

// --- Helper function to write CSV data ---
function writeCsv(filePath, data, header = false) {
    const parser = new Parser({ fields: Object.keys(data[0]), header });
    const csvData = parser.parse(data);
    fs.appendFileSync(filePath, '\n' + csvData + '\n'); // Append to the file
}

// --- Function to get retention for a single channel ---
async function getCustomRetention(channelId){
    // --- Initialize Slack Bolt App ---
    // We want to use a different app to add Enterprise Data Retention to a channel
    const app = new App({
        token: process.env.EDR_BOT_TOKEN,
        signingSecret: process.env.EDR_SIGNING_SECRET
    });
    
    if (!channelId || typeof channelId !== 'string' || !channelId.trim()) {
        console.warn(`⚠️ Skipping invalid channel ID: ${channelId}`);
        return;
    }

    const trimmedChannelId = channelId.trim();

    try {
        // API Method: admin.conversations.setCustomRetention
        // https://api.slack.com/methods/admin.conversations.getCustomRetention
        response = await app.client.admin.conversations.getCustomRetention({
            token: process.env.EDR_USER_TOKEN,
            channel_id: trimmedChannelId
        });
        console.log(`✅ getCustomRetention(${trimmedChannelId}) = ${response.duration_days}`)
        console.log(response)
        return response.duration_days;
    } catch (error) {
        // Catch errors during the API call (network, auth issues, etc.)
        console.error(`❌ Could not get custom retention on ${trimmedChannelId}:`, error.message);
        // Bolt wraps Slack API errors in error.data
        if (error.data && error.data.error) {
             console.error(`   Slack API Error Details: ${error.data.error}`);
             if (error.data.error === 'missing_scope') {
                console.error('   Hint: Ensure your bot token has the "admin.conversations:write" scope.');
             } else if (error.data.error === 'paid_teams_only') {
                 console.error('   Hint: This feature might require a paid Slack plan (e.g., Business+, Enterprise Grid).');
             } else if (error.data.error === 'feature_not_enabled') {
                  console.error('   Hint: Custom message retention might need to be enabled at the Org/Workspace level first.');
             } else if (error.data.error === 'ratelimited') {
                console.warn('   Rate limited. Consider increasing the apiCallDelay.');
             }
        }
    }
}

// --- Function to set retention for a single channel ---
async function setChannelRetention(channelId, durationDays) {
    // --- Initialize Slack Bolt App ---
    // We only need the token for making direct API calls, no need for signing secret or receiver
    // ERROR: 
    //  AppInitializationError: signingSecret is required to initialize the default receiver. Set signingSecret or use a custom receiver. You can find your Signing Secret in your Slack App Settings.
    const app = new App({
        token: token,
        signingSecret: slackSigningSecret
    });
    
    if (!channelId || typeof channelId !== 'string' || !channelId.trim()) {
        console.warn(`⚠️ Skipping invalid channel ID: ${channelId}`);
        return;
    }
    const trimmedChannelId = channelId.trim();
    console.log(`⏳ Attempting to set retention for channel ${trimmedChannelId} to ${durationDays} days...`);

    try {
        // API Method: admin.conversations.setCustomRetention
        // https://api.slack.com/methods/admin.conversations.setCustomRetention
        const response = await app.client.admin.conversations.setCustomRetention({
            // Need to explicitly pass user token due to scope needed for this method
            token: slackUserToken, // Pass token explicitly if needed, though Bolt usually handles it
            channel_id: trimmedChannelId,
            duration_days: durationDays
        });

        // Slack API responses usually have an 'ok' boolean field
        if (response.ok) {
            const successData = [{
                channel_id: trimmedChannelId
            }];
            writeCsv(csvSuccessPath, successData, !fs.existsSync(csvSuccessPath));
            console.log(`✅ Successfully set retention for channel ${trimmedChannelId} to ${durationDays} days.`);
        } else {
            // Log the specific error returned by the Slack API
            console.error(`❌ Failed to set retention for channel ${trimmedChannelId}. Slack API Error: ${response.error || 'Unknown error'}`);
            const failureData = [{ channel_id: trimmedChannelId, error: response.error || 'Unknown error' }];
            writeCsv(csvFailedPath, failureData, !fs.existsSync(csvFailedPath));
        }
    } catch (error) {
        // Catch errors during the API call (network, auth issues, etc.)
        console.error(`❌ Error processing channel ${trimmedChannelId}:`, error.message);
        // Bolt wraps Slack API errors in error.data
        if (error.data && error.data.error) {
             console.error(`   Slack API Error Details: ${error.data.error}`);
             if (error.data.error === 'missing_scope') {
                console.error('   Hint: Ensure your bot token has the "admin.conversations:write" scope.');
             } else if (error.data.error === 'paid_teams_only') {
                 console.error('   Hint: This feature might require a paid Slack plan (e.g., Business+, Enterprise Grid).');
             } else if (error.data.error === 'feature_not_enabled') {
                  console.error('   Hint: Custom message retention might need to be enabled at the Org/Workspace level first.');
             } else if (error.data.error === 'ratelimited') {
                console.warn('   Rate limited. Consider increasing the apiCallDelay.');
             }
            const failureData = [{ channel_id: trimmedChannelId, error: error.message }];
            writeCsv(csvFailedPath, failureData, !fs.existsSync(csvFailedPath));
        }
    }
}

// --- Main function to read CSV and process channels ---
async function processChannelsFromCsv() {
    console.log(`Reading channel IDs from: ${csvFilePath}`);
    console.log(`Target retention period: ${retentionDays} days`);
    console.log('-----------------------------------------');

    const channelsToProcess = [];
    let headerChecked = false;
    let foundHeader = false;

    fs.createReadStream(csvFilePath)
        .pipe(csv({ // Make headers lowercase for easier matching
            mapHeaders: ({ header }) => header.trim().toLowerCase()
        }))
        .on('headers', (headers) => { // Check if the required header exists
            console.log('CSV Headers found:', headers);
            if (headers.includes(csvChannelIdHeader.toLowerCase())) {
                foundHeader = true;
                headerChecked = true;
            } else {
                console.error(`Error: CSV file (<span class="math-inline">\{csvFilePath\}\) must contain a header named '</span>{csvChannelIdHeader}'. Found headers: ${headers.join(', ')}`);
                // Stop processing if header is missing
                this.destroy(); // 'this' refers to the stream here
                process.exit(1);
            }
        })
        .on('data', (row) => {
            // Extract channel ID based on the specified header name (already lowercased)
            const channelId = row[csvChannelIdHeader.toLowerCase()];
            if (channelId) {
                channelsToProcess.push(channelId);
            } else {
                console.warn(`⚠️ Skipping row with missing channel ID in column '${csvChannelIdHeader}':`, row);
            }
        })
        .on('end', async () => {
            if (!headerChecked && !foundHeader) {
                // This case might happen for empty files or files without headers processed correctly
                console.error(`Error: Could not confirm the presence of the header '${csvChannelIdHeader}' in ${csvFilePath}. Is the file empty or malformed?`);
                process.exit(1);
                return; // Exit if header check failed
            }
            if (channelsToProcess.length === 0) {
                console.log('No channel IDs found in the CSV file to process.');
                return;
            }

            console.log(`\nFound ${channelsToProcess.length} channel IDs in the CSV.`);
            console.log('Starting retention update process...');
            console.log('-----------------------------------------');

            // Process channels one by one with a delay
            for (const channelId of channelsToProcess) {
                await getCustomRetention(channelId);
                // Wait for a short period before the next API call
                if (apiCallDelay > 0) {
                    await new Promise(resolve => setTimeout(resolve, apiCallDelay));
                }
            }

            console.log('-----------------------------------------');
            console.log('✅ Finished processing all channels from the CSV file.');
        })
        .on('error', (error) => {
            console.error('Error reading or parsing CSV file:', error);
        });
}

// --- Run the script ---

processChannelsFromCsv();