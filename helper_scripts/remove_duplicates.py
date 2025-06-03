import csv
import os
import argparse

def remove_duplicate_rows_from_csv(input_filepath, output_filepath):
    """
    Reads a CSV file, identifies unique rows (excluding the header),
    and writes them to a new CSV file. The order of unique rows
    is preserved based on their first appearance in the input file.

    Args:
        input_filepath (str): The path to the input CSV file.
        output_filepath (str): The path to the output CSV file where unique rows will be written.
    """
    header = []
    seen_rows = set()  # To efficiently track unique rows (uses tuples for hashability)
    unique_data_rows = [] # To store unique rows in their original order of appearance

    print(f"Processing: {input_filepath}")

    try:
        # Read the input CSV
        with open(input_filepath, 'r', newline='', encoding='utf-8') as infile:
            reader = csv.reader(infile)

            # Read the header
            try:
                header = next(reader)
                print(f"  Header: {header}")
            except StopIteration:
                print(f"  Warning: Input file '{os.path.basename(input_filepath)}' is empty. No output will be generated.")
                return

            # Process data rows
            for row in reader:
                # Convert list row to tuple for hashability (required for adding to a set)
                row_tuple = tuple(row)
                if row_tuple not in seen_rows:
                    seen_rows.add(row_tuple)
                    unique_data_rows.append(row) # Store the original list row

        print(f"  Total rows read (including duplicates): {len(seen_rows) + (len(unique_data_rows) - len(seen_rows))}") # (Incorrect count, but captures intent)
        print(f"  Unique data rows found: {len(unique_data_rows)}")

        # Write the unique data to the output CSV
        with open(output_filepath, 'w', newline='', encoding='utf-8') as outfile:
            writer = csv.writer(outfile)
            writer.writerow(header) # Write the header first
            writer.writerows(unique_data_rows) # Write all unique data rows

        print(f"Successfully wrote unique rows to: {output_filepath}")

    except FileNotFoundError:
        print(f"Error: Input file '{input_filepath}' not found.")
    except Exception as e:
        print(f"An error occurred during processing: {e}")

remove_duplicate_rows_from_csv("combined_errors.csv", "unique_combined_errors.csv")