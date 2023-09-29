import markdown
import bleach
import sys

if len(sys.argv) != 3:
    print("usage: python script.py <input markdown file> <output html file>")
    sys.exit(1)

input_markdown_file = sys.argv[1]
output_html_file = sys.argv[2]

with open(input_markdown_file, 'r') as f:
    text = f.read()

# converts the markdown to html
html = markdown.markdown(text)

# makes links that begin with https:// clickable
html_with_links = bleach.linkify(html)

# defines a template that should be at the beginning of the html
start_template = '''<!DOCTYPE html>
<html lang="en">

<!-- this file is automatically updated when README.md is updated, please don't modify it -->

<head>
    <title>readme</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link rel="icon" type="image/png" href="/favicon.png">
    <style>
        body {
            background-color: black;
            color: white;
            font-size: 20px;
            font-family: sans-serif;
        }

        a {
            color: white;
        }
    </style>
</head>
<body>
'''

# defines a template that should be at the end
end_template = '''
</body>
</html>
'''

# combines them
final_html = start_template + html_with_links + end_template

with open(output_html_file, 'w') as f:
    f.write(final_html)
