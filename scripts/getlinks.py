from bs4 import BeautifulSoup
from urllib.request import Request, urlopen
import re
import sys
from urllib.parse import urljoin

if len(sys.argv) < 2:
    print("Please provide a URL.")
    sys.exit(1)

url = sys.argv[1]

headers = {'User-Agent': 'Mozilla/5.0'}

req = Request(url, headers=headers)

html_page = urlopen(req)

soup = BeautifulSoup(html_page, "html.parser")

links = []
for link in soup.findAll('a'):
    href = link.get('href')
    if href:
        full_url = urljoin(url, href)
        links.append(full_url)

formatted_links = '\n'.join(links)
print(formatted_links)
