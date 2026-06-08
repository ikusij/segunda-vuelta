import requests
import json

from constants import HEADERS

DEPARTAMENTOS = "https://resultadoelectoral.onpe.gob.pe/presentacion-backend/ubigeos/departamentos?idEleccion=10&idAmbitoGeografico={}"
PROVINCIAS = "https://resultadoelectoral.onpe.gob.pe/presentacion-backend/ubigeos/provincias?idEleccion=10&idAmbitoGeografico={}&idUbigeoDepartamento={}"
DISTRITO = "https://resultadoelectoral.onpe.gob.pe/presentacion-backend/ubigeos/distritos?idEleccion=10&idAmbitoGeografico={}&idUbigeoProvincia={}"

def write_hierarchy():

    def load_departamentos():
        
        data = []

        for ambito_geografico in [1, 2]:
            
            try:
                rsp = requests.get(DEPARTAMENTOS.format(ambito_geografico), headers=HEADERS, timeout=1)
                rsp.raise_for_status()
                departamentos = rsp.json().get('data', [])
            except Exception as e:
                print(f"Failed to load departamentos for ambito {ambito_geografico}: {e}")
                continue

            for idx, departamento in enumerate(departamentos):

                print(f"Ambito {ambito_geografico}: {idx + 1}/{len(departamentos)} {departamento['nombre']}")

                departamento_info = {
                    "nombre": departamento["nombre"],
                    "ubigeo": departamento["ubigeo"],
                    "provincias": load_provincias(ambito_geografico, departamento["ubigeo"])
                }

                data.append(departamento_info)

        return data

    def load_provincias(ambito_geografico, ubigeo_departamento):
        
        try:
            rsp = requests.get(PROVINCIAS.format(ambito_geografico, ubigeo_departamento), headers=HEADERS, timeout=1)
            rsp.raise_for_status()
            provincias = rsp.json().get('data', [])
        except Exception as e:
            print(f"Failed to load provincias {ubigeo_departamento} for ambito {ambito_geografico}: {e}")
            return []

        provincias_data = []
        for provincia in provincias:
            
            provincia_info = {
                "nombre": provincia["nombre"],
                "ubigeo": provincia["ubigeo"],
                "distritos": load_distritos(ambito_geografico, provincia["ubigeo"])
            }

            provincias_data.append(provincia_info)

        return provincias_data

    def load_distritos(ambito_geografico, ubigeo_provincia):
        
        try:
            rsp = requests.get(DISTRITO.format(ambito_geografico, ubigeo_provincia), headers=HEADERS, timeout=1)
            rsp.raise_for_status()
            distritos = rsp.json().get('data', [])
        except Exception as e:
            print(f"Failed to load distritos {ubigeo_provincia} for ambito {ambito_geografico}: {e}")
            return []

        distritos_data = []
        for distrito in distritos:
            distrito_info = {
                "nombre": distrito["nombre"],
                "ubigeo": distrito["ubigeo"]
            }
            distritos_data.append(distrito_info)
        return distritos_data

    with open("hierarchy.json", "w", encoding="utf-8") as f:
        json.dump(load_departamentos(), f, ensure_ascii=False, indent=2)

def write_nombre_ubigeo():

    with open("hierarchy.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    zone_dict = {}

    for departamento in data:
        dept_name = departamento["nombre"]
        dept_distritos = []

        for provincia in departamento.get("provincias", []):
            prov_name = provincia["nombre"]
            prov_distritos = []

            for distrito in provincia.get("distritos", []):
                dist_name = distrito["nombre"]
                dist_ubigeo = distrito["ubigeo"]

                # Save district name mapped to its UBIGEO as a single-item list
                # If duplicate name, accumulate
                if dist_name in zone_dict:
                    # In case of collision, append if different
                    if dist_ubigeo not in zone_dict[dist_name]:
                        zone_dict[dist_name].append(dist_ubigeo)
                else:
                    zone_dict[dist_name] = [dist_ubigeo]

                prov_distritos.append(dist_ubigeo)
                dept_distritos.append(dist_ubigeo)

            # Province: If province name already used (e.g. as district), keep previous under disambiguated name
            if prov_name in zone_dict:
                # Only add if not already done
                alt_name = f"{prov_name} (DISTRITO)"
                if alt_name not in zone_dict:
                    zone_dict[alt_name] = zone_dict[prov_name]

            zone_dict[prov_name] = prov_distritos

        # Department: similar disambiguation
        if dept_name in zone_dict:
            alt_name = f"{dept_name} (PROVINCIA)"
            if alt_name not in zone_dict:
                zone_dict[alt_name] = zone_dict[dept_name]

        zone_dict[dept_name] = dept_distritos

    with open("nombre_ubigeo.json", "w", encoding="utf-8") as f:
        json.dump(zone_dict, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    write_hierarchy()
    write_nombre_ubigeo()
