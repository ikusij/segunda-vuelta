import requests
from constants import HEADERS
from time import sleep
from random import uniform
from threading import Lock, Event

BASE = "https://resultadosegundavuelta.onpe.gob.pe/presentacion-backend"
PARTICIPANTES_URL = BASE + "/eleccion-presidencial/participantes-ubicacion-geografica-nombre?tipoFiltro=ubigeo_nivel_03&idAmbitoGeografico={ambito}&ubigeoNivel1={dep}&ubigeoNivel2={prov}&ubigeoNivel3={dist}&idEleccion=10"
TOTALES_URL = BASE + "/resumen-general/totales?idAmbitoGeografico={ambito}&idEleccion=10&tipoFiltro=ubigeo_nivel_03&idUbigeoDepartamento={dep}&idUbigeoProvincia={prov}&idUbigeoDistrito={dist}"

TOTALES_DROP_KEYS = { "idUbigeoDepartamento", "idUbigeoProvincia", "idUbigeoDistrito", "idUbigeoDistritoElectoral", "porcentajeVotosEmitidos", "porcentajeVotosValidos" }

session = requests.Session()
session.headers.update(HEADERS)

_pause_event = Event()
_pause_event.set()  # start unpaused
_pause_lock = Lock()

def _pause_all(seconds=30):
    with _pause_lock:
        if not _pause_event.is_set():
            return  # already pausing
        print(f"\n🚫 CF blocked — pausing all requests for {seconds}s...")
        _pause_event.clear()
        sleep(seconds)
        _pause_event.set()
        print("✅ Resuming...")

def _ubigeos(ubigeo_distrito):
    distrito = int(ubigeo_distrito)
    ubigeos = {
        "dep":  str(distrito // 10000 * 10000),
        "prov": str(distrito // 100 * 100),
        "dist": str(distrito),
    }
    ubigeos["ambito"] = "2" if distrito >= 260000 else "1"
    return ubigeos

def _get(url, **ubigeo_kwargs):
    _pause_event.wait()  # block here if paused
    rsp = session.get(url.format(**ubigeo_kwargs), timeout=10)
    rsp.raise_for_status()
    if "application/json" not in rsp.headers.get("Content-Type", ""):
        _pause_all() 
        raise ValueError("CF_BLOCKED")
    return rsp.json()

def load_participantes(ubigeo_distrito):
    ub = _ubigeos(ubigeo_distrito)
    participantes = _get(PARTICIPANTES_URL, **ub).get("data", [])
    candidatos = {
        (p["nombreCandidato"] or "VOTOS NULOS"): p.get("totalVotosValidos", 0)
        for p in participantes
    }
    return candidatos

def load_totales(ubigeo_distrito):
    ub = _ubigeos(ubigeo_distrito)
    data = _get(TOTALES_URL, **ub).get("data", {})
    return { k: v for k, v in data.items() if k not in TOTALES_DROP_KEYS }

def fetch(ubigeo_distrito):

    totales = load_totales(ubigeo_distrito)
    candidatos = load_participantes(ubigeo_distrito)

    votos_emitidos = totales.get("totalVotosEmitidos", 0)
    actas_contabilizadas = totales.get("actasContabilizadas", 0)

    votos_restantes = (
        int(votos_emitidos * (100 / actas_contabilizadas - 1))
        if actas_contabilizadas else 0
    )

    suma_votos_validos = sum(candidatos.values())
    candidatos["VOTOS EN BLANCO"] = max(0, votos_emitidos - suma_votos_validos)

    return {
        "ubigeo_distrito": ubigeo_distrito,
        "pendientesJee": totales.get("pendientesJee", 0),
        "votosEmitidos": votos_emitidos,
        "votosRestantes": votos_restantes,
        "candidatos": candidatos,
    }