echo "Running apply-retention.js: Applys the retention policy to each channel from channels-to-process.csv"
echo "Logs successes to log/log_successful_channel.csv and fails to log/log_fail_channel.csv"
echo ""
node apply-retention.js
echo ""
echo "Running apply-channel-description.js: Checks the retention policy of each channel from log_successful_channel.csv"
echo ""
node apply-channel-description.js