import os
import re

def remove_age_gate(file_path):
    with open(file_path, 'r') as file:
        content = file.read()

    new_content = re.sub(
        r'<script id="age_check_preload" src="https:\/\/diyhrt\.wiki\/age-check\.js">.*?<\/script>', '', content, flags=re.DOTALL)

    with open(file_path, 'w') as file:
        file.write(new_content)

directory_path = 'diyhrt.wiki'

for filename in os.listdir(directory_path):
    file_path = os.path.join(directory_path, filename)
    if os.path.isfile(file_path):
        remove_age_gate(file_path)
