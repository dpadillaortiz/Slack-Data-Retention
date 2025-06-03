#!/bin/bash

# --- Script to Search for APPLY_USER_TOKEN in .env files within Subdirectories ---
# This script iterates through subdirectories of a specified parent directory.
# In each subdirectory, it searches for the string "APPLY_USER_TOKEN" specifically
# within files named ".env".
# When found, it prints the subdirectory name followed by the entire line
# containing "APPLY_USER_TOKEN".

# 1. Prompt for the parent directory
echo "--- APPLY_USER_TOKEN Search Script ---"
echo "This script will search for 'APPLY_USER_TOKEN' in .env files within subdirectories."
read -p "Please enter the path to the parent directory you want to search: " PARENT_DIR

# 2. Validate the provided directory
if [[ ! -d "$PARENT_DIR" ]]; then
    echo "Error: Directory '$PARENT_DIR' does not exist or is not a directory."
    echo "Exiting script."
    exit 1
fi

echo "Searching for 'APPLY_USER_TOKEN' in .env files in subdirectories of: $PARENT_DIR"
echo "----------------------------------------------------"

# 3. Find .env files and process them
#    - `find "$PARENT_DIR" -type f -name ".env"`: Finds all regular files named ".env"
#      within the PARENT_DIR and its subdirectories.
#    - `-exec grep -H "APPLY_USER_TOKEN" {} +`: Executes grep on the found .env files.
#      - `-H`: Prints the file name for each match.
#      - `{}`: Placeholder for the found file names.
#      - `+`: Passes multiple file names to a single grep command for efficiency.
#    - `while IFS= read -r line`: Reads each line of grep's output.

find "$PARENT_DIR" -type f -name ".env" -exec grep -H "APPLY_USER_TOKEN" {} + 2>/dev/null | while IFS= read -r line; do
    # Example line from grep: /path/to/parent_dir/subdir_name/.env:APPLY_USER_TOKEN=some_value

    # Extract the full file path and the matching line content
    FILE_PATH=$(echo "$line" | cut -d':' -f1)
    MATCHING_LINE=$(echo "$line" | cut -d':' -f2-) # Get everything after the first colon

    # Extract the subdirectory name from the file path
    # We need to remove the PARENT_DIR prefix and the file name part.
    # dirname gets the directory part, then basename gets the last component.
    SUBDIR_FULL_PATH=$(dirname "$FILE_PATH")
    SUBDIR_NAME=$(basename "$SUBDIR_FULL_PATH")

    # If the .env file is directly in PARENT_DIR, SUBDIR_NAME will be the PARENT_DIR's basename.
    # We want the immediate subdirectory.
    # Let's refine this to ensure we get the immediate subdirectory name relative to PARENT_DIR.
    RELATIVE_PATH=${FILE_PATH#"$PARENT_DIR/"} # Remove PARENT_DIR/ prefix
    # Now, get the first component of the relative path, which is the subdirectory name
    # or the file name if it's directly in PARENT_DIR.
    # We want the actual subdirectory name, not the file name.
    # So, we take the part before the first '/' after the PARENT_DIR.
    if [[ "$RELATIVE_PATH" == *"/"* ]]; then
        # It's in a subdirectory
        SUBDIR_NAME=$(echo "$RELATIVE_PATH" | cut -d'/' -f1)
    else
        # It's a file directly in PARENT_DIR, so use the PARENT_DIR's name as the "directory_name"
        SUBDIR_NAME=$(basename "$PARENT_DIR")
    fi

    # Print the output in the desired format
    echo "${SUBDIR_NAME}: ${MATCHING_LINE}"

done

echo "----------------------------------------------------"
echo "Search complete."
exit 0
