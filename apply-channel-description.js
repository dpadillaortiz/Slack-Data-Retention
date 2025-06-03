require('dotenv').config();
const { App } = require('@slack/bolt');
const fs = require('fs');
const csv = require('csv-parser');
const { Parser } = require('json2csv');

// --- Configuration ---
const token = process.env.EDR_BOT_TOKEN;
const slackSigningSecret = process.env.EDR_SIGNING_SECRET;
const slackUserToken = process.env.EDR_USER_TOKEN;
const csvFilePath = process.env.CSV_SUCCESSFUL_CHANNELS;
const retentionDays = parseInt(process.env.RETENTION_DAYS, 10);

const csvFailedPath = 'logs/confirmed-failed_channels.csv';     // New path for failed channels
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

// --- Initialize Slack Bolt App ---
const app = new App({
    token: token,
    signingSecret: slackSigningSecret
});

// --- Helper function to write CSV data ---
function writeCsv(filePath, data, header = false) {
    const parser = new Parser({ fields: Object.keys(data[0]), header });
    const csvData = parser.parse(data);
    fs.appendFileSync(filePath, '\n' +csvData + '\n'); // Append to the file
}

// Apply the channel description
function appendDescription(current, addition) {
    lastIndex = current.length - 1
    targetIndex = (current.length - addition.length) + 1;
    sliced_current = current.substring(0,targetIndex);
    return `${sliced_current} ${addition}`;
}

async function inviteUser(channelId) {
    if (!channelId || typeof channelId !== 'string' || !channelId.trim()) {
        console.warn(`⚠️ Skipping invalid channel ID: ${channelId}`);
        return;
    }
    const trimmedChannelId = channelId.trim();
    // --- Initialize Slack Bolt App ---
    // We want to use a different app to add Enterprise Data Retention to a channel
    const app = new App({
        token: process.env.ADMIN_BOT_TOKEN,
        signingSecret: process.env.ADMIN_SIGNING_SECRET
    });
    console.log(`⏳ Attempting to add Enterprise Data Retention app to channel ${channelId}`);
    try {
        await app.client.admin.conversations.invite({
            // Need to explicitly pass user token due to scope needed for this method
            token: process.env.ADMIN_USER_TOKEN,
            channel_id: trimmedChannelId,
            user_ids: [`${process.env.EDR_USER_ID}`] 
        });
        console.log("✅ Added EDR to channel.");
    } catch (error) {
        // Catch errors during the API call (network, auth issues, etc.)
        console.warn("⚠️ App may already be installed on channel or user id does not exist.")
    }
}

async function getDataRetention(channelId){
    if (!channelId || typeof channelId !== 'string' || !channelId.trim()) {
        console.warn(`⚠️ Skipping invalid channel ID: ${channelId}`);
        return;
    }
    const trimmedChannelId = channelId.trim();
    try {
        // API Method: admin.conversations.setCustomRetention
        // https://api.slack.com/methods/admin.conversations.getCustomRetention
        response = await app.client.admin.conversations.getCustomRetention({
            token: slackUserToken,
            channel_id: trimmedChannelId
        });
        console.log(`✅ getCustomRetention(${trimmedChannelId}) = ${response.duration_days} `)
        console.log(response)
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
            const failureData = [{ channel_id: trimmedChannelId, error: error.message }];
            writeCsv(csvFailedPath, failureData, !fs.existsSync(csvFailedPath));
        }
    }
}

async function setChannelDescription(channelId, durationDays) {
    const durationYears = durationDays/365;
    const retentionDescription = `(Data retention : ${durationYears} Years)`
    console.log(`⏳ Attempting to update the channel description for \"${channelId}\"`);

    try {
        // https://api.slack.com/methods/conversations.info
        // Retrieve information about a conversation.
        response = await app.client.conversations.info({
            channel: channelId, 
        });

        const channelIdDescription = response.channel.purpose.value
        const isChannelArchived = response.channel.is_archived

        if (isChannelArchived){
            throw new Error(`The channel, ${channelId}, is archived.`)
        } 
        
        if (channelIdDescription.length == 0) {
            // The channel description is empty. 
            await app.client.conversations.setPurpose({
                channel: channelId, 
                purpose: retentionDescription
            });
            console.log(`✅ Description applied for ${channelId}`);
        } else if ((channelIdDescription.length + retentionDescription.length) > 250) {
            newDescription = appendDescription(channelIdDescription, retentionDescription);
            await app.client.conversations.setPurpose({
                channel: channelId, 
                purpose: newDescription
            });
            console.log(`✅ Description modified for ${channelId}`);
        } else {
            await app.client.conversations.setPurpose({
                channel: channelId, 
                purpose: `${channelIdDescription} ${retentionDescription}`
            });
            console.log(`✅ Description appended for ${channelId}`);
        }
    } catch (error) {
        // Catch errors during the API call (network, auth issues, etc.)
        console.error(`❌ Could not setup description`)
        console.error(error);
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
            const failureData = [{ channel_id: channelId, error: error.message }];
            writeCsv(csvFailedPath, failureData, !fs.existsSync(csvFailedPath));
        }
    }
}

// --- Function to set retention for a single channel ---
async function getChannelRetention(channelId, durationDays) {
    if (!channelId || typeof channelId !== 'string' || !channelId.trim()) {
        console.warn(`⚠️ Skipping invalid channel ID: ${channelId}`);
        return;
    }
    const trimmedChannelId = channelId.trim();
    console.log(`⏳ Attempting to check if retention for channel ${trimmedChannelId} is ${durationDays} days...`);
    try {
        // API Method: admin.conversations.setCustomRetention
        // https://api.slack.com/methods/admin.conversations.getCustomRetention
        const response = await app.client.admin.conversations.getCustomRetention({
            token: slackUserToken,
            channel_id: trimmedChannelId
        });
        console.log(`✅ getCustomRetention(${trimmedChannelId}) = ${durationDays} `)
        
        setChannelDescription(trimmedChannelId, response.duration_days)
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
            const failureData = [{ channel_id: trimmedChannelId, error: error.message }];
            writeCsv(csvFailedPath, failureData, !fs.existsSync(csvFailedPath));
        }
    }
}

// --- Helper Function for User ID Conversion ---
function formatUserIdsForSetPrefs(userIdList) {
    /**
     * Converts a list of user IDs (e.g., ['U1234', 'U5678'])
     * into the format required by admin.conversations.setConversationPrefs
     * (e.g., 'user:U1234,user:U5678').
     *
     * Args:
     * userIdList (Array<string>): A list of Slack User IDs.
     *
     * Returns:
     * string: A comma-separated string of formatted user IDs, or an empty string if the list is empty.
     */
    if (!userIdList || userIdList.length === 0) {
        return "";
    }
    return userIdList.map(uid => `user:${uid}`).join(',');
}

// --- Main Functions for Your Task ---

async function getChannelPostingPrefs(channelId) {
    /**
     * Retrieves the current posting preferences for a given channel.
     *
     * Args:
     * channelId (string): The ID of the channel.
     *
     * Returns:
     * Object: An object containing 'type' (Array<string>) and 'user' (Array<string>) lists
     * for who_can_post, or null if prefs cannot be retrieved.
     */
    try {
        response = await app.client.admin.conversations.getConversationPrefs({ channel_id: channelId, token: slackUserToken });
        if (response.ok) {
            const prefs = response.prefs || {};
            const whoCanPost = prefs.who_can_post || { type: [], user: [] };
            console.log(`Retrieved posting preferences for channel '${channelId}': ${JSON.stringify(whoCanPost)}`);
            return whoCanPost;
        } else {
            const errorMsg = `Error getting conversation prefs for '${channelId}': ${response.error}`;
            console.log(errorMsg);
            return null;
        }
    } catch (e) {
        const errorMsg = `Exception when getting conversation prefs for '${channelId}': ${e.message}`;
        console.log(errorMsg);
        return null;
    }
}

async function updateChannelPostingPermissionsForApp(channelId, edrAppUserId) {
    /**
     * Adds the EDR app's user ID to the channel's posting permissions without removing existing users.
     *
     * Args:
     * channelId (string): The ID of the channel to update.
     * edrAppUserId (string): The User ID of your EDR app (e.g., 'A1234567890').
     *
     * Returns:
     * boolean: True if permissions were updated successfully, False otherwise.
     */
    const currentPrefs = await getChannelPostingPrefs(channelId);

    if (currentPrefs === null) {
        console.log(`Could not retrieve current preferences for channel '${channelId}'. Aborting update.`);
        return false;
    }

    // Get current allowed users
    const currentAllowedUsers = new Set(currentPrefs.user || []);
    const currentAllowedTypes = new Set(currentPrefs.type || []);

    // Add EDR app user ID if not already present
    if (!currentAllowedUsers.has(edrAppUserId)) {
        currentAllowedUsers.add(edrAppUserId);
        console.log('info', `Adding EDR app user '${edrAppUserId}' to allowed posters list for '${channelId}'.`);
    } else {
        console.log('info', `EDR app user '${edrAppUserId}' is already in the allowed posters list for '${channelId}'.`);
    }

    // Convert the updated user list to the required string format
    const formattedUsersString = formatUserIdsForSetPrefs(Array.from(currentAllowedUsers));

    // Convert allowed types to the required string format
    const formattedTypesStringParts = Array.from(currentAllowedTypes).map(pType => `type:${pType}`);

    // Combine types and users into a single string for the 'who_can_post' preference value
    let combinedPrefsString = "";
    if (formattedTypesStringParts.length > 0) {
        combinedPrefsString += formattedTypesStringParts.join(',');
    }
    if (formattedUsersString) {
        if (combinedPrefsString) {
            combinedPrefsString += ',';
        }
        combinedPrefsString += formattedUsersString;
    }

    if (!combinedPrefsString) {
        console.log('warn', `No effective 'who_can_post' preferences to set for channel '${channelId}'. Aborting.`);
        return false;
    }

    // The 'prefs' parameter needs to be a stringified JSON object
    const prefsPayload = JSON.stringify({ who_can_post: combinedPrefsString });
    console.log('info', `Attempting to set prefs for '${channelId}' with payload: ${prefsPayload}`);

    try {
        const response = await app.client.admin.conversations.setConversationPrefs({
            channel_id: channelId,
            token: slackUserToken,
            prefs: prefsPayload
        });
        if (response.ok) {
            console.log('info', `Successfully updated posting permissions for channel '${channelId}'.`);
            return true;
        } else {
            const errorMsg = `Error setting conversation prefs for '${channelId}': ${response.error}`;
            console.log('error', errorMsg);
            return false;
        }
    } catch (e) {
        const errorMsg = `Exception when setting conversation prefs for '${channelId}': ${e.message}`;
        console.log('error', errorMsg);
        return false;
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
                await inviteUser(channelId);
                // Wait for a short period before the next API call
                if (apiCallDelay > 0) {
                    await new Promise(resolve => setTimeout(resolve, apiCallDelay));
                }
                await getChannelRetention(channelId, retentionDays);
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