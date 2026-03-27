#!/bin/bash

# --- Simple Directory Iterator Script ---
# This script demonstrates how to iterate through files and directories
# within a specified directory using a 'for' loop.

# 1. Prompt for the directory to iterate
echo "--- Directory Iterator Script ---"
read -p "Please enter the path to the directory you want to iterate through: " TARGET_DIR

# 2. Validate the provided directory
if [[ ! -d "$TARGET_DIR" ]]; then
    echo "Error: Directory '$TARGET_DIR' does not exist or is not a directory."
    echo "Exiting script."
    exit 1
fi

echo "Iterating through contents of: $TARGET_DIR"
echo "----------------------------------------------------"

# 3. Iterate through each item in the directory
#    The '*' wildcard expands to all files and directories (non-hidden)
#    within the TARGET_DIR.
#    We use "$TARGET_DIR"/* to ensure it works correctly even if TARGET_DIR
#    contains spaces.

for item in "$TARGET_DIR"/*; do
    # New check: Does the TARGET_DIR contain any immediate subdirectories?
    # We use 'find' to look for directories (-type d) at depth 1 (-maxdepth 1)
    # relative to TARGET_DIR. '-print -quit' makes it efficient by stopping
    # after the first subdirectory is found.
    # The '2>/dev/null' redirects any error messages (e.g., permission denied)
    # from 'find' to prevent them from affecting the check.
    if [[ -z "$(find "$TARGET_DIR" -mindepth 1 -maxdepth 1 -type d -print -quit 2>/dev/null)" ]]; then
        echo "Info: The directory '$TARGET_DIR' does not contain any immediate subdirectories."
        # --- Start of 'do something' block when no subdirectories are found ---
        echo "Action: Performing a specific task because no subdirectories were detected."
        # Use parameter expansion to remove the TARGET_DIR/ prefix
        # ${item#"$TARGET_DIR/"} removes the shortest match of "$TARGET_DIR/" from the front of $item
        RELATIVE_ITEM_PATH="${item#"$TARGET_DIR/"}"
        python3 create_error_batch.py $TARGET_DIR
        # --- End of 'do something' block ---
    else
        echo "Info: The directory '$item' contains one or more subdirectories."
        echo "$item" | ./search_for_errors.sh

    fi
done

echo "----------------------------------------------------"
echo "Iteration complete."
exit 0
