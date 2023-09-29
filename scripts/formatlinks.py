import sys

def remove_trailing_spaces(line):
    return line.rstrip()

def remove_duplicate_lines(file_path):
    lines_seen = set()
    output_lines = []

    with open(file_path, 'r') as file:
        for line in file:
            cleaned_line = remove_trailing_spaces(line)

            if cleaned_line.startswith("https://diyhrt.cafe") and cleaned_line not in lines_seen:
                lines_seen.add(cleaned_line)
                output_lines.append(line)

    with open(file_path, 'w') as file:
        file.writelines(output_lines)

# Usage example
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Please provide the file path as an argument.")
    else:
        file_path = sys.argv[1]
        remove_duplicate_lines(file_path)
