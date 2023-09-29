import os
import argparse

# May need to do "pip install mako"
from mako.template import Template


INDEX_TEMPLATE = r"""
<html>
<head>
    <style>
        body {
            background-color: black;
            color: white;
            font-size: 25px;
        }

        a {
            color: white;
        }
    </style>
</head>
<body>
    <h2>${header}</h2>
    <p>
        % for name in names:
            <a href="${name}">${name}</a><br>
        % endfor
    </p>
</body>
</html>
"""

EXCLUDED = ['index.html']


def generate_index(directory):
    fnames = [fname for fname in sorted(os.listdir(directory)) if fname not in EXCLUDED]
    header = os.path.basename(directory)
    index_content = Template(INDEX_TEMPLATE).render(names=fnames, header=header)

    with open(os.path.join(directory, 'index.html'), 'w') as index_file:
        index_file.write(index_content)

#    subdirectories = [subdir for subdir in fnames if os.path.isdir(os.path.join(directory, subdir))]
#    for subdir in subdirectories:
#        generate_index(os.path.join(directory, subdir))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory")
    args = parser.parse_args()
    generate_index(args.directory)


if __name__ == '__main__':
    main()
