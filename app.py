import json
import os

import altair as alt
import pandas as pd
import streamlit as st

from monte_carlo import (
    MonteCarloConfig,
    aggregate_province,
    make_synthetic_result,
    monte_carlo_simulation,
)

# ── Constants ────────────────────────────────────────────────────────────────

TODOS_OPTS = {
    "PERU_Y_EXTRANJERO": "— Todos (Perú + Extranjero) —",
    "PERU_SOLO":          "— Solo Perú —",
    "EXTRANJERO_SOLO":    "— Solo Extranjero —",
}
TODOS = TODOS_OPTS["PERU_Y_EXTRANJERO"]  # default variable for backcompat
TIMESERIES_FILE = "timeseries.csv"
CACHE_TTL = 1800

# Departamentos del Perú (fuente: INEI/ONPE) — EXCLUYE continentes/agrupaciones internacionales
PERU_DEPARTMENTS = [
    'AMAZONAS', 'ANCASH', 'APURÍMAC', 'APURIMAC', 'AREQUIPA', 'AYACUCHO', 'CAJAMARCA', 'CALLAO',
    'CUSCO', 'HUANCAVELICA', 'HUÁNUCO', 'HUANUCO', 'ICA', 'JUNÍN', 'JUNIN', 'LA LIBERTAD',
    'LAMBAYEQUE', 'LIMA', 'LORETO', 'MADRE DE DIOS', 'MOQUEGUA', 'PASCO', 'PIURA', 'PUNO',
    'SAN MARTÍN', 'SAN MARTIN', 'TACNA', 'TUMBES', 'UCAYALI'
]
# Se usan variantes con y sin tilde para máxima tolerancia a fuentes mixtas

# ── Data loaders ─────────────────────────────────────────────────────────────

@st.cache_data(show_spinner=False, ttl=CACHE_TTL)
def load_bundle() -> dict:
    with open("bundle.json", encoding="utf-8") as f:
        return json.load(f)


@st.cache_data(show_spinner=False, ttl=CACHE_TTL)
def load_geo_data() -> tuple[dict, dict, dict, dict]:
    with open("hierarchy.json", encoding="utf-8") as f:
        output = json.load(f)

    ubigeo_names: dict[str, str] = {}
    ubigeo_to_dept: dict[str, str] = {}
    ubigeo_to_prov: dict[str, str] = {}
    hierarchy: dict[str, dict[str, list[tuple[str, str]]]] = {}

    for dept in output:
        dept_name = dept["nombre"]
        hierarchy[dept_name] = {}
        for prov in dept.get("provincias", []):
            prov_name = prov["nombre"]
            pairs = sorted(
                [(d["nombre"], str(d["ubigeo"])) for d in prov.get("distritos", [])],
                key=lambda x: x[0],
            )
            if pairs:
                hierarchy[dept_name][prov_name] = pairs
            for dist in prov.get("distritos", []):
                uid = str(dist["ubigeo"])
                ubigeo_names[uid] = dist["nombre"]
                ubigeo_to_dept[uid] = dept_name
                ubigeo_to_prov[uid] = prov_name

    return ubigeo_names, ubigeo_to_dept, ubigeo_to_prov, hierarchy


@st.cache_data(show_spinner=False, ttl=CACHE_TTL)
def load_null_votes_data(bundle: dict) -> pd.DataFrame:
    with open("hierarchy.json", encoding="utf-8") as f:
        output = json.load(f)

    ubigeo_to_geo: dict[str, dict] = {
        str(dist["ubigeo"]): {
            "Departamento": dept["nombre"],
            "Provincia": prov["nombre"],
            "Distrito": dist["nombre"],
        }
        for dept in output
        for prov in dept.get("provincias", [])
        for dist in prov.get("distritos", [])
    }

    excluded = {"VOTOS NULOS", "VOTOS EN BLANCO"}
    rows = []
    for ubigeo, district in bundle.items():
        emitidos = district.get("votosEmitidos", 0)
        if emitidos == 0:
            continue
        candidatos = district.get("candidatos", {})
        nulos = candidatos.get("VOTOS NULOS", 0)
        valid = {k: v for k, v in candidatos.items() if k not in excluded}
        leader = max(valid, key=valid.get) if valid else "—"
        geo = ubigeo_to_geo.get(ubigeo, {"Departamento": "—", "Provincia": "—", "Distrito": ubigeo})
        rows.append({
            "Departamento": geo["Departamento"],
            "Provincia": geo["Provincia"],
            "Distrito": geo["Distrito"],
            "Ubigeo": ubigeo,
            "Votos emitidos": emitidos,
            "Votos nulos": nulos,
            "% nulos": nulos / emitidos * 100,
            "Líder": leader,
        })

    return pd.DataFrame(rows)


# ── Simulation ───────────────────────────────────────────────────────────────

def skip_reason(d: dict) -> str:
    if d["votosEmitidos"] == 0:
        return "Sin votos contabilizados"
    cand_sum = sum(v for k, v in d["candidatos"].items() if k != "VOTOS EN BLANCO")
    if abs(cand_sum - d["votosEmitidos"]) > d["votosEmitidos"] * 0.05:
        return f"Datos inconsistentes (candidatos: {cand_sum:,} vs emitidos: {d['votosEmitidos']:,})"
    return "Desconocido"


def run_simulation(
    ids: tuple,
    n_simulations: int,
    confidence_level: float,
    prior: str,
    votes_per_acta: int,
    compute_breakdown: bool = False,
    geo_grouping: str = "none",
):
    bundle = load_bundle()
    ubigeo_names, ubigeo_to_dept, ubigeo_to_prov, _ = load_geo_data()

    data = [bundle[uid] for uid in ids if uid in bundle]
    fetch_failures = [
        {"Ubigeo": uid, "Distrito": uid, "Error": "No encontrado en el bundle"}
        for uid in ids
        if uid not in bundle
    ]

    if not data:
        return None, [], [], fetch_failures, []

    # Step 1: simulate valid districts
    results = [
        monte_carlo_simulation(
            d,
            MonteCarloConfig(
                n_simulations=n_simulations,
                prior=prior,
                confidence_level=confidence_level,
                random_seed=i,
            ),
        )
        for i, d in enumerate(data)
    ]

    # Step 2: build province/department aggregates
    province_valid: dict[str, list] = {}
    department_valid: dict[str, list] = {}
    for d, r in zip(data, results):
        if r is None:
            continue
        uid = str(d["ubigeo_distrito"])
        province_valid.setdefault(uid[:4], []).append(r)
        department_valid.setdefault(uid[:2], []).append(r)

    province_aggregates = {pc: aggregate_province(rs) for pc, rs in province_valid.items()}
    department_aggregates = {dc: aggregate_province(rs) for dc, rs in department_valid.items()}

    # Step 3: synthesize skipped districts
    estimated, truly_skipped, synthetic_results = [], [], []
    for d, r in zip(data, results):
        if r is not None:
            continue
        uid = str(d["ubigeo_distrito"])
        prov_agg = province_aggregates.get(uid[:4])
        dept_agg = department_aggregates.get(uid[:2])
        fallback_agg = prov_agg or dept_agg
        fallback_label = "provincia" if prov_agg else ("departamento" if dept_agg else None)
        total_votes = d.get("pendientesJee", 0) * votes_per_acta
        synthetic = make_synthetic_result(fallback_agg, total_votes)
        row = {
            "Ubigeo": uid,
            "Distrito": ubigeo_names.get(uid, "—"),
            "Motivo": skip_reason(d),
            "Distribución usada": fallback_label or "—",
            "Votos est. (actas)": total_votes,
        }
        if synthetic is not None:
            synthetic_results.append(synthetic)
            estimated.append(row)
        else:
            truly_skipped.append(row)

    # Step 4: final aggregation
    all_results = [r for r in results if r is not None] + synthetic_results
    if not all_results:
        return None, estimated, truly_skipped, fetch_failures, []

    final_agg = aggregate_province(all_results)

    # Step 5: optional geographic breakdown
    breakdown = None
    if compute_breakdown and geo_grouping != "none":
        geo_label, key_fn = {
            "district":   ("Distrito",     lambda uid: ubigeo_names.get(uid, uid)),
            "province":   ("Provincia",    lambda uid: ubigeo_to_prov.get(uid, uid)),
            "department": ("Departamento", lambda uid: ubigeo_to_dept.get(uid, uid)),
        }[geo_grouping]

        top_candidates = [c.name for c in final_agg.candidates[:5]]
        synthetic_iter = iter(synthetic_results)
        district_pairs = [
            (str(d["ubigeo_distrito"]), r if r is not None else next(synthetic_iter, None))
            for d, r in zip(data, results)
        ]

        groups: dict[str, list] = {}
        for uid, r in district_pairs:
            if r is not None:
                groups.setdefault(key_fn(uid), []).append(r)

        breakdown_rows = []
        for geo_name, group_results in sorted(groups.items()):
            grp = aggregate_province(group_results)
            cand_map = {c.name: c for c in grp.candidates}
            row = {
                geo_label: geo_name,
                "% contabilizado": grp.pct_counted,
                "Votos contabilizados": grp.votes_counted,
                "Total votos": grp.total_votes,
                "Ganador proyectado": grp.projected_winner.name,
            }
            for name in top_candidates:
                c = cand_map.get(name)
                if c:
                    proj = int(c.projected_share * grp.total_votes)
                    row[f"{name} — proy."] = proj
                    row[f"{name} — adic."] = proj - c.votes_counted
            breakdown_rows.append(row)

        breakdown = (geo_label, breakdown_rows)

    # Free large numpy arrays
    for r in all_results:
        r.raw_finals = None
    final_agg.raw_finals = None

    return final_agg, estimated, truly_skipped, fetch_failures, breakdown


_run_simulation_cached = st.cache_data(
    show_spinner=False, max_entries=10, ttl=CACHE_TTL
)(run_simulation)


# ── Page setup ───────────────────────────────────────────────────────────────

st.set_page_config(page_title="ONPE Probabilidad de Victoria", layout="wide")
st.title("ONPE — Probabilidad de Victoria Electoral")

bundle = load_bundle()
ubigeo_names, ubigeo_to_dept, ubigeo_to_prov, hierarchy = load_geo_data()
null_votes_df = load_null_votes_data(bundle)

active_tab = st.sidebar.radio(
    "Vista",
    ["Simulación Monte Carlo", "Serie de Tiempo"],
    label_visibility="collapsed",
)
st.sidebar.markdown("---")

# Helper: detect perú sololista, extranjero only, or mixed
def is_peruvian_dept(dept_name):
    return any(
        dept_name.upper() == pdname or dept_name.title() == pdname
        for pdname in PERU_DEPARTMENTS
    )

extranjero_depts = [d for d in hierarchy.keys() if not is_peruvian_dept(d)]
peruvian_deps   = [d for d in sorted(hierarchy.keys()) if is_peruvian_dept(d)]

# ── Tab: Monte Carlo ─────────────────────────────────────────────────────────

if active_tab == "Simulación Monte Carlo":
    n_simulations    = st.sidebar.number_input("Simulaciones", min_value=500, max_value=2000, value=500, step=100)
    confidence_level = st.sidebar.slider("Nivel de confianza", 0.80, 0.99, 0.95, step=0.01)
    prior_option     = st.sidebar.selectbox("Prior", ["flat", "jeffreys"])
    votes_per_acta   = st.sidebar.number_input(
        "Votos por acta",
        min_value=150, max_value=300, value=220, step=1,
        help="Número estimado de votos por acta. Se usa para calcular votos pendientes en distritos sin datos.",
    )

    col_todos, col_dep, col_prov, col_dist = st.columns([2, 3, 3, 3])

    # NUEVO SELECTOR de TODOS
    with col_todos:
        todos_choice = st.selectbox(
            "Ámbito",
            [
                TODOS_OPTS["PERU_Y_EXTRANJERO"],
                TODOS_OPTS["PERU_SOLO"],
                TODOS_OPTS["EXTRANJERO_SOLO"],
            ],
            help="Elija si desea simular votos nacionales, solo Perú, o solo extranjero.",
            key="todos_choice"
        )

    with col_dep:
        # La lista de departamentos depende de todos_choice
        if todos_choice == TODOS_OPTS["PERU_Y_EXTRANJERO"]:
            available_deps = sorted(hierarchy.keys())
        elif todos_choice == TODOS_OPTS["PERU_SOLO"]:
            available_deps = peruvian_deps
        elif todos_choice == TODOS_OPTS["EXTRANJERO_SOLO"]:
            available_deps = sorted(extranjero_depts)
        else:
            available_deps = sorted(hierarchy.keys())
        dept_sel = st.selectbox(
            "Departamento",
            [TODOS] + available_deps,
            help={
                TODOS_OPTS["PERU_Y_EXTRANJERO"]:  "Departamentos ubicados en Perú y agrupaciones tipo extranjero.",
                TODOS_OPTS["PERU_SOLO"]:          "Solo departamentos ubicados en Perú.",
                TODOS_OPTS["EXTRANJERO_SOLO"]:    "Solo agrupaciones o zonas del extranjero.",
            }[todos_choice],
            key="dept_sel"
        )

    with col_prov:
        if dept_sel == TODOS:
            st.selectbox("Provincia", [TODOS], disabled=True, key="prov_sel_disabled")
            prov_sel = TODOS
        else:
            prov_sel = st.selectbox("Provincia", [TODOS] + sorted(hierarchy[dept_sel].keys()), key="prov_sel")

    with col_dist:
        if prov_sel == TODOS:
            st.selectbox("Distrito", [TODOS], disabled=True, key="dist_sel_disabled")
            dist_sel, dist_ubigeo = TODOS, None
        else:
            pairs = hierarchy[dept_sel][prov_sel]
            dist_sel = st.selectbox("Distrito", [TODOS] + [name for name, _ in pairs], key="dist_sel")
            dist_ubigeo = next((uid for name, uid in pairs if name == dist_sel), None)

    if st.button("Ejecutar simulación", key="run_sim"):
        # Resolve ubigeos from selection based on TODOS selector
        if dist_sel != TODOS and dist_ubigeo:
            ids = [dist_ubigeo]
        elif prov_sel != TODOS:
            ids = [uid for _, uid in hierarchy[dept_sel][prov_sel]]
        elif dept_sel != TODOS:
            ids = [uid for pairs in hierarchy[dept_sel].values() for _, uid in pairs]
        else:
            # Todos a nivel nacional, perú, o extranjero según todos_choice
            if todos_choice == TODOS_OPTS["PERU_Y_EXTRANJERO"]:
                # Nacional: todo el hierarchy
                ids = [
                    uid
                    for dept_name, dept_provs in hierarchy.items()
                    for prov_name, pairs in dept_provs.items()
                    for _, uid in pairs
                ]
            elif todos_choice == TODOS_OPTS["PERU_SOLO"]:
                # Perú solo, solo departamentos peruanos
                ids = [
                    uid
                    for dept_name, dept_provs in hierarchy.items()
                    if dept_name in peruvian_deps
                    for prov_name, pairs in dept_provs.items()
                    for _, uid in pairs
                ]
            elif todos_choice == TODOS_OPTS["EXTRANJERO_SOLO"]:
                # Extranjero solo, solo agrupaciones no-perú
                ids = [
                    uid
                    for dept_name, dept_provs in hierarchy.items()
                    if dept_name in extranjero_depts
                    for prov_name, pairs in dept_provs.items()
                    for _, uid in pairs
                ]
            else:
                # Backcompatible national
                ids = [
                    uid
                    for dept_name, dept_provs in hierarchy.items()
                    for prov_name, pairs in dept_provs.items()
                    for _, uid in pairs
                ]

        if not ids:
            st.error("No se encontraron ubigeos para esta selección.")
            st.stop()

        # ZONE LABEL REFLECTS SCOPE
        if dept_sel != TODOS:
            zone_label = dept_sel
        elif todos_choice == TODOS_OPTS["PERU_Y_EXTRANJERO"]:
            zone_label = "Nacional (Perú+Extranjero)"
        elif todos_choice == TODOS_OPTS["PERU_SOLO"]:
            zone_label = "Sólo Perú"
        elif todos_choice == TODOS_OPTS["EXTRANJERO_SOLO"]:
            zone_label = "Extranjero"
        else:
            zone_label = "Nacional"

        geo_grouping = (
            "none"       if dist_sel != TODOS else
            "district"   if prov_sel != TODOS else
            "province"   if dept_sel != TODOS else
            "department"
        )

        sim_fn = _run_simulation_cached if dist_sel == TODOS else run_simulation
        with st.spinner("Ejecutando simulación Monte Carlo…"):
            result, estimated, truly_skipped, fetch_failures, breakdown = sim_fn(
                ids=tuple(ids),
                n_simulations=int(n_simulations),
                confidence_level=confidence_level,
                prior=prior_option,
                votes_per_acta=int(votes_per_acta),
                compute_breakdown=dist_sel == TODOS and int(n_simulations) <= 1000,
                geo_grouping=geo_grouping,
            )

        if result is None:
            st.error("Sin datos utilizables — todos los distritos fueron omitidos y no se pudo inferir una distribución provincial.")
            st.stop()

        ci_pct = int(result.confidence_level * 100)
        st.subheader(f"Resultados — {zone_label}")

        # Summary metrics
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Votos contabilizados", f"{result.votes_counted:,}")
        c2.metric("Votos restantes",      f"{result.votes_remaining:,}")
        c3.metric("Total de votos",       f"{result.total_votes:,}")
        c4.metric("% contabilizado",      f"{result.pct_counted:.1%}")

        # Candidate table
        pct_cols = ["Porcentaje actual", "Porcentaje proyectado", f"IC inferior ({ci_pct}%)", f"IC superior ({ci_pct}%)"]
        int_cols = ["Votos contabilizados", "Votos proyectados", "Votos adicionales"]

        DISPLAY_CANDIDATES = {
            "KEIKO SOFIA FUJIMORI HIGUCHI",
            "ROBERTO HELBERT SANCHEZ PALOMINO",
            "VOTOS NULOS",
            "VOTOS EN BLANCO",
        }

        rows = []
        for c in result.candidates:
            if c.name not in DISPLAY_CANDIDATES:
                continue

            proj_votes = int(c.projected_share * result.total_votes)

            rows.append({
                "Candidato":                c.name,
                "Votos contabilizados":     c.votes_counted,
                "Porcentaje actual":        c.current_share,
                "Porcentaje proyectado":    c.projected_share,
                f"IC inferior ({ci_pct}%)": c.ci_low,
                f"IC superior ({ci_pct}%)": c.ci_high,
                "Votos proyectados":        proj_votes,
                "Votos adicionales":        proj_votes - c.votes_counted,
            })

        styled = (
            pd.DataFrame(rows).set_index("Candidato").style
            .format({col: "{:.2%}" for col in pct_cols})
            .format({col: "{:,}"   for col in int_cols})
        )
        st.dataframe(styled, use_container_width=True)

        winner = result.projected_winner
        st.success(
            f"**Ganador proyectado:** {winner.name} — "
            f"probabilidad de victoria {winner.win_probability:.1%}, "
            f"porcentaje proyectado {winner.projected_share:.2%}"
        )

        # ── Desglose geográfico ──────────────────────────────────────────────────
        if breakdown:
            geo_label, breakdown_rows = breakdown
            with st.expander(f"Desglose por {geo_label.lower()} ({len(breakdown_rows)})"):
                bdf = pd.DataFrame(breakdown_rows).set_index(geo_label)
                pct_b = ["% contabilizado"]
                int_b = ["Votos contabilizados", "Total votos"] + [c for c in bdf.columns if "proy." in c or "adic." in c]
                st.dataframe(
                    bdf.style
                        .format({col: "{:.1%}" for col in pct_b})
                        .format({col: "{:,}"   for col in int_b}),
                    use_container_width=True,
                )

        if estimated:
            with st.expander(f"Distritos estimados con distribución provincial ({len(estimated)})"):
                st.write(
                    "Estos distritos no tenían votos contabilizados. "
                    "Sus totales de votos fueron estimados con `votasRestantesEstimadoConActas` "
                    "y su distribución fue inferida de los distritos válidos de la misma provincia o departamento."
                )
                st.dataframe(pd.DataFrame(estimated), use_container_width=True, hide_index=True)

        if truly_skipped:
            with st.expander(f"Distritos excluidos completamente ({len(truly_skipped)} — sin datos provinciales disponibles)"):
                st.write(
                    "Estos distritos no tenían datos válidos ni agregado provincial del cual inferir, "
                    "por lo que fueron excluidos de la simulación."
                )
                st.dataframe(pd.DataFrame(truly_skipped), use_container_width=True, hide_index=True)

        if fetch_failures:
            with st.expander(f"Distritos no encontrados en el bundle ({len(fetch_failures)})"):
                st.write("Estos distritos no fueron encontrados en el bundle de datos y fueron excluidos.")
                st.dataframe(pd.DataFrame(fetch_failures), use_container_width=True, hide_index=True)

# ── Tab: Serie de Tiempo ─────────────────────────────────────────────────────

if active_tab == "Serie de Tiempo":
    if not os.path.exists(TIMESERIES_FILE):
        st.info("No hay datos de serie de tiempo. Ejecuta `run_simulation.py --date '...'` para generar snapshots.")
        st.stop()

    ts_df = pd.read_csv(TIMESERIES_FILE, parse_dates=["timestamp"])
    all_candidates = sorted(ts_df["candidate"].unique())
    selected = st.multiselect(
        "Candidatos",
        options=all_candidates,
        default=[c for c in all_candidates if any(k in c for k in ("FUJIMORI", "SANCHEZ", "LÓPEZ ALIAGA", "LOPEZ ALIAGA"))],
    )
    filtered_ts = ts_df[ts_df["candidate"].isin(selected)] if selected else ts_df

    def ts_line_chart(data: pd.DataFrame, y_field: str, y_title: str) -> alt.VConcatChart:
        brush = alt.selection_interval(encodings=["x"])
        color = alt.Color("candidate:N", title="Candidato")
        x_axis = alt.Axis(format="%d/%m %H:%M")

        detail = (
            alt.Chart(data)
            .transform_filter(brush)
            .mark_line(point=True)
            .encode(
                x=alt.X("timestamp:T", title="Fecha/Hora", axis=x_axis),
                y=alt.Y(f"{y_field}:Q", title=y_title, scale=alt.Scale(zero=False)),
                color=color,
                tooltip=[
                    alt.Tooltip("timestamp:T", title="Fecha/Hora", format="%Y-%m-%d %H:%M"),
                    alt.Tooltip("candidate:N", title="Candidato"),
                    alt.Tooltip(f"{y_field}:Q", title=y_title, format=","),
                ],
            )
            .properties(height=300)
        )

        overview = (
            alt.Chart(data)
            .mark_line()
            .encode(
                x=alt.X("timestamp:T", title="", axis=x_axis),
                y=alt.Y(f"{y_field}:Q", title="", axis=None),
                color=color,
            )
            .properties(height=60)
            .add_params(brush)
        )

        return detail & overview

    st.subheader("Votos proyectados a lo largo del tiempo")
    st.altair_chart(ts_line_chart(filtered_ts, "projected_votes", "Votos proyectados"), use_container_width=True)

    st.subheader("Votos contabilizados a lo largo del tiempo")
    st.altair_chart(ts_line_chart(filtered_ts, "votes_counted", "Votos contabilizados"), use_container_width=True)

    st.subheader("% de votos evaluados a lo largo del tiempo")
    pct_df = ts_df.drop_duplicates("timestamp")[["timestamp", "pct_counted"]].copy()
    pct_df["pct_counted"] *= 100
    pct_brush = alt.selection_interval(encodings=["x"])

    pct_detail = (
        alt.Chart(pct_df)
        .transform_filter(pct_brush)
        .mark_line(point=True)
        .encode(
            x=alt.X("timestamp:T", title="Fecha/Hora", axis=alt.Axis(format="%d/%m %H:%M")),
            y=alt.Y("pct_counted:Q", title="% contabilizado", scale=alt.Scale(zero=False)),
            tooltip=[
                alt.Tooltip("timestamp:T", title="Fecha/Hora", format="%Y-%m-%d %H:%M"),
                alt.Tooltip("pct_counted:Q", title="% contabilizado", format=".2f"),
            ],
        )
        .properties(height=300)
    )

    pct_overview = (
        alt.Chart(pct_df)
        .mark_line()
        .encode(
            x=alt.X("timestamp:T", title="", axis=alt.Axis(format="%d/%m %H:%M")),
            y=alt.Y("pct_counted:Q", title="", axis=None),
        )
        .properties(height=60)
        .add_params(pct_brush)
    )

    st.altair_chart(pct_detail & pct_overview, use_container_width=True)

    with st.expander("Datos crudos"):
        st.dataframe(
            ts_df.sort_values(["timestamp", "candidate"]),
            use_container_width=True,
            hide_index=True,
        )