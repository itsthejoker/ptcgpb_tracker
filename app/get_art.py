import os
from io import BytesIO
import time

import httpx
from bs4 import BeautifulSoup
from PIL import Image

url = "https://pocket.limitlesstcg.com/cards"
card_url = "https://limitlesstcg.nyc3.cdn.digitaloceanspaces.com/pocket/{set_id}/{set_id}_{card_num}_EN_SM.webp"

resp = httpx.get(url)

soup = BeautifulSoup(resp.content, 'html.parser')
set_ids = [el.split("/")[-1] for el in set([z.get('href') for z in soup.main.find_all("a")])]

for set_id in set_ids:
    os.makedirs(f"resources/card_imgs/{set_id}", exist_ok=True)

for set_id in set_ids:
    for card_num in range(1, 500):
        print(f"{set_id}_{card_num}")
        img_url = card_url.format(set_id=set_id, card_num=str(card_num).zfill(3))
        r = httpx.get(img_url)
        if "AccessDenied" in str(r.content):
            break
        i = Image.open(BytesIO(r.content))
        i.save(f"resources/card_imgs/{set_id}/{set_id}_{card_num}.webp")
