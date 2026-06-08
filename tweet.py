from requests_oauthlib import OAuth1
from dotenv import load_dotenv
import requests
import os

load_dotenv()

CONSUMER_KEY = os.getenv("CONSUMER_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
ACCESS_TOKEN_SECRET = os.getenv("ACCESS_TOKEN_SECRET")

AUTH = OAuth1(CONSUMER_KEY, SECRET_KEY, ACCESS_TOKEN, ACCESS_TOKEN_SECRET)

URL = "https://api.twitter.com/2/tweets"

TEMPLATE = """
🗳️ PERÚ 2026 | Resultados en vivo

ACTUALIZADO: {}

CONTADO
🟠 FUERZA POPULAR —— {:,}
🟢 JP — {:,}

ESTIMADO
🟠 FUERZA POPULAR —— {:,}
🟢 JP — {:,}

#EleccionesPeru #2daVuelta
""".strip()

def create_tweet(fecha, fp_cont, jp_cont, fp_est, jp_est):

    payload = { "text": TEMPLATE.format(fecha, fp_cont, jp_cont, fp_est, jp_est) }
    print(requests.post(URL, json=payload, headers={ "Content-Type": "application/json" }, auth=AUTH))

