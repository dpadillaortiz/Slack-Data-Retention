import csv
import os
import sys


def clean_csv_field(value_str):
    """
    Cleans a string value from a CSV field by:
    1. Stripping leading/trailing whitespace.
    It preserves the original character casing.

    Note: Standard CSV quoting (e.g., "value") is handled automatically
    by the csv module and does NOT require additional cleaning here.
    """
    if isinstance(value_str, str):
        return value_str.strip()
    return value_str # Return non-string values as is

def process_csv_file(file_path):
    """
    Reads a single CSV file, extracts 'channel_id' and 'error' data,
    and includes the original file name and its parent folder name.
    """
    extracted_rows = []
    
    # Extract file name and parent folder name
    file_name = os.path.basename(file_path)
    parent_folder_full_path = os.path.dirname(file_path)
    # Get the name of the immediate parent folder. If the file is directly
    # in the input_directory, this will be the input_directory's name itself.
    parent_folder_name = os.path.basename(parent_folder_full_path)
    
    print(f"Processing: {parent_folder_name}/{file_name}")

    try:
        with open(file_path, 'r', newline='', encoding='utf-8') as infile:
            reader = csv.reader(infile)

            # --- Read and Identify Headers ---
            try:
                raw_header_row = next(reader)
                cleaned_and_lowercased_headers = [clean_csv_field(h).lower() for h in raw_header_row]
            except StopIteration:
                print(f"  Warning: {file_name} is empty or has no header. Skipping.")
                return []

            channel_id_col_idx = -1
            error_col_idx = -1

            for i, header_name in enumerate(cleaned_and_lowercased_headers):
                if header_name == 'channel_id':
                    channel_id_col_idx = i
                elif header_name == 'error':
                    error_col_idx = i

            if channel_id_col_idx == -1 or error_col_idx == -1:
                print(f"  Warning: '{file_name}' missing 'channel_id' or 'error' column. Skipping.")
                return []

            # --- Process Data Rows ---
            for row in reader:
                if len(row) > max(channel_id_col_idx, error_col_idx):
                    channel_id = clean_csv_field(row[channel_id_col_idx])
                    error = clean_csv_field(row[error_col_idx])

                    extracted_rows.append({
                        'channel_id': channel_id,
                        'error': error,
                        'file_name': f"{parent_folder_name}/{file_name}" # Base file name (e.g., my_log.csv)
                    })
                else:
                    print(f"  Warning: Row in '{file_name}' has fewer columns than expected: {row}. Skipping this row.")

    except FileNotFoundError:
        print(f"Error: File not found at {file_path}. Skipping.")
    except Exception as e:
        print(f"Error processing {file_name}: {e}. Skipping this file.")

    return extracted_rows

# batch_3_complete/confirmed-failed_channels.csv

def main(input_directory):
    """
    Main function to run the CSV processing.
    It sets up input/output paths and orchestrates file processing.
    """
    # Define input and output paths relative to where the script is run
    script_dir = os.path.dirname(os.path.abspath(__file__))
    input_directory = os.path.join(script_dir, input_directory)
    output_csv_path = os.path.join(script_dir, 'combined_errors.csv')

    # Create the input directory if it doesn't exist and advise user
    if not os.path.exists(input_directory):
        os.makedirs(input_directory)
        print(f"Created input directory: '{input_directory}'")
        print("Please place your CSV files into this folder and run the script again.")
        return

    all_collected_data = []
    output_headers = ['channel_id', 'error', 'file_name']

    # Find all CSV files in the input directory
    csv_files_to_process = [f for f in os.listdir(input_directory) if f.lower().endswith('.csv')]

    if not csv_files_to_process:
        print(f"No CSV files found in '{input_directory}'.")
        print("Make sure your CSVs are in this directory.")
        return

    # Process each found CSV file
    for csv_filename in csv_files_to_process:
        full_file_path = os.path.join(input_directory, csv_filename)
        data_from_file = process_csv_file(full_file_path)
        all_collected_data.extend(data_from_file)

    if not all_collected_data:
        print("No data was extracted from any CSV files. No output file will be created.")
        return

    # Write all collected data to the output CSV
    try:
        with open(output_csv_path, 'a', newline='', encoding='utf-8') as outfile:
            writer = csv.DictWriter(outfile, fieldnames=output_headers)
            writer.writeheader() # Write the header row for the output file
            writer.writerows(all_collected_data)

        print(f"\nProcessing complete!")
        print(f"All data combined into: '{output_csv_path}'")
        print(f"Total rows written: {len(all_collected_data)}")

    except Exception as e:
        print(f"An error occurred while writing the output file '{output_csv_path}': {e}")


if __name__ == "__main__":
    print(sys.argv[1])
    main(sys.argv[1])
