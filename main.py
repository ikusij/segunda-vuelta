from fetch_all import fetch_all
from datetime import datetime
from time import sleep
import requests

from tweet import create_tweet
from run_simulation import run_national_simulation
from constants import HEADERS

URL = "https://resultadosegundavuelta.onpe.gob.pe/presentacion-backend/resumen-general/totales?idEleccion=10&tipoFiltro=eleccion"

def timestamp_to_words(timestamp):
    
    """
    Convierte un timestamp Unix (milisegundos o segundos) a una fecha legible en palabras.
    Ejemplo de salida: '07 DE JUNIO DE 2026, 10:00:00 a. m.'
    Ejemplo de entrada: 1780846200639
    """

    dt = datetime.fromtimestamp(timestamp)
    
    meses = [
        "ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO",
        "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"
   
    ]

    day = f"{dt.day:02d}"
    month = meses[dt.month - 1]
    year = dt.year
    hour = dt.strftime("%H:%M")
    
    if hora.startswith('0'):
        hora = hora[1:]
    
    return f"{year}-{month}-{day} {hour}"

def heartbeat():
    
    try:
        
        response = requests.get(URL, headers=HEADERS)
        response.raise_for_status()
        json_response = response.json()
        
        timestamp = int(json_response["data"]["fechaActualizacion"]) // 1000

        return timestamp

    except requests.RequestException as e:
        
        print(f"Error fetching results: {e}")

if __name__ == "__main__":
    
    prev_timestamp = None

    while True:
        
        timestamp = heartbeat()

        if prev_timestamp is None or timestamp != prev_timestamp:
            fetch_all()
            prev_timestamp = timestamp

        sleep(60)
