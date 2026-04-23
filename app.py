"""
Streamlit aplikace pro analýzu přihlášek na SŠ Futurum.
Spuštění: streamlit run app.py
"""
from __future__ import annotations

import hmac
import sys
from pathlib import Path

from collections import Counter

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# Přidáme adresář skriptu do PYTHONPATH, abychom mohli importovat analyza_prihlasek
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from analyza_prihlasek import (
    CISELNIK_OBORU,
    CACHE_SKOLY,
    MAX_PRIORIT,
    MSMT_REJSTRIK_URL,
    NASE_SKOLA_IZO,
    NASE_SKOLA_NAZEV,
    nacti_ciselnik_skol_z_csv,
    nacti_ciselnik_skol_z_msmt,
    nacti_data,
    najdi_vstupni_csv,
    preloz_izo,
    preloz_obor,
)

# =============================================================================
# Konfigurace stránky
# =============================================================================

st.set_page_config(
    page_title=f"Přihlášky – {NASE_SKOLA_NAZEV}",
    page_icon="🎓",
    layout="wide",
)


# =============================================================================
# Heslová brána
# =============================================================================

def check_password() -> bool:
    """Vrátí True, pokud uživatel zadal správné heslo."""

    def password_entered():
        if hmac.compare_digest(
            st.session_state.get("password", ""),
            st.secrets.get("app_password", ""),
        ):
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if st.session_state.get("password_correct", False):
        return True

    st.title(f"🎓 Přihlášky – {NASE_SKOLA_NAZEV}")
    st.text_input("Heslo", type="password", on_change=password_entered, key="password")
    if "password_correct" in st.session_state and not st.session_state["password_correct"]:
        st.error("😕 Nesprávné heslo")
    return False


if not check_password():
    st.stop()


# =============================================================================
# Načtení a cachování dat
# =============================================================================


@st.cache_data(show_spinner="Načítám data z CSV...")
def load_csv() -> pd.DataFrame:
    csv_path = najdi_vstupni_csv(SCRIPT_DIR)
    return nacti_data(csv_path)


@st.cache_data(show_spinner="Stahuji číselník škol z MŠMT...")
def load_ciselnik_skol() -> dict[str, str]:
    return nacti_ciselnik_skol_z_msmt(CACHE_SKOLY, MSMT_REJSTRIK_URL)


@st.cache_data(show_spinner="Sestavuji číselník z CSV...")
def load_ciselnik_csv(_df: pd.DataFrame) -> dict[str, str]:
    return nacti_ciselnik_skol_z_csv(_df)


@st.cache_data(show_spinner="Obohacuji tabulku...")
def build_enriched(df: pd.DataFrame, _cs_msmt: dict, _cs_csv: dict) -> pd.DataFrame:
    """Přidá sloupce skola_nazev_X a obor_nazev_X."""
    out = df.copy()
    for i in range(1, MAX_PRIORIT + 1):
        col_izo = f"skola_izo_{i}"
        col_obor = f"kod_oboru_{i}"
        if col_izo in out.columns:
            out[f"skola_nazev_{i}"] = out[col_izo].apply(
                lambda x, m=_cs_msmt, c=_cs_csv: preloz_izo(x, m, c)
            )
        if col_obor in out.columns:
            out[f"obor_nazev_{i}"] = out[col_obor].apply(preloz_obor)
    return out


def get_konkurence(df: pd.DataFrame, priorita: int | None, cs_msmt: dict, cs_csv: dict):
    """Vrátí (df_skoly, df_skoly_obory, pocet_uchazecú) pro danou prioritu.
    Pokud priorita=None, vrátí konkurenci napříč všemi prioritami."""

    # Najít uchazeče, kteří mají naši školu na dané prioritě (nebo kdekoliv)
    if priorita is not None:
        col_izo = f"skola_izo_{priorita}"
        if col_izo not in df.columns:
            return None, None, 0
        maska = df[col_izo].astype(str).str.strip() == NASE_SKOLA_IZO
    else:
        # Kdekoliv v prioritách
        izo_cols = [f"skola_izo_{i}" for i in range(1, MAX_PRIORIT + 1) if f"skola_izo_{i}" in df.columns]
        maska = df[izo_cols].astype(str).apply(lambda row: row.str.strip().eq(NASE_SKOLA_IZO).any(), axis=1)

    uchazeci = df[maska]
    pocet = len(uchazeci)
    if pocet == 0:
        return None, None, 0

    zaznamy = []
    for i in range(1, MAX_PRIORIT + 1):
        ci = f"skola_izo_{i}"
        co = f"kod_oboru_{i}"
        if ci not in uchazeci.columns:
            continue
        for _, row in uchazeci.iterrows():
            izo_val = str(row.get(ci, "")).strip()
            obor_val = str(row.get(co, "")).strip()
            if izo_val and izo_val != "nan" and izo_val != NASE_SKOLA_IZO:
                zaznamy.append({
                    "priorita_konkurenta": i,
                    "izo_skoly": izo_val,
                    "nazev_skoly": preloz_izo(izo_val, cs_msmt, cs_csv),
                    "kod_oboru": obor_val if obor_val != "nan" else "",
                    "nazev_oboru": preloz_obor(obor_val) if obor_val and obor_val != "nan" else "",
                })

    if not zaznamy:
        return None, None, pocet

    df_k = pd.DataFrame(zaznamy)

    skoly = (
        df_k.groupby(["nazev_skoly"])
        .size()
        .reset_index(name="pocet")
        .sort_values("pocet", ascending=False)
        .reset_index(drop=True)
    )

    skoly_obory = (
        df_k.groupby(["nazev_skoly", "kod_oboru", "nazev_oboru"])
        .size()
        .reset_index(name="pocet")
        .sort_values("pocet", ascending=False)
        .reset_index(drop=True)
    )

    return skoly, skoly_obory, pocet


# =============================================================================
# Načtení dat
# =============================================================================

df_raw = load_csv()
cs_msmt = load_ciselnik_skol()
cs_csv = load_ciselnik_csv(df_raw)
df_full = build_enriched(df_raw, cs_msmt, cs_csv)


# =============================================================================
# Pomocné funkce pro filtraci podle oboru na naší škole
# =============================================================================

def nase_obory_z_dat(df_in: pd.DataFrame) -> list[str]:
    """Vrátí seřazený seznam názvů oborů, které uchazeči volí na naší škole."""
    obory = set()
    for i in range(1, MAX_PRIORIT + 1):
        ci = f"skola_izo_{i}"
        cn = f"obor_nazev_{i}"
        if ci in df_in.columns and cn in df_in.columns:
            mask = df_in[ci].astype(str).str.strip() == NASE_SKOLA_IZO
            vals = df_in.loc[mask, cn].dropna().unique()
            obory.update(v for v in vals if v and v != "nan")
    return sorted(obory)


def filtruj_podle_oboru(df_in: pd.DataFrame, obor: str) -> pd.DataFrame:
    """Filtruje uchazeče, kteří mají na naší škole zadaný obor.
    Pokud obor == 'Celkem', vrátí všechny."""
    if obor == "Celkem":
        return df_in
    mask = pd.Series(False, index=df_in.index)
    for i in range(1, MAX_PRIORIT + 1):
        ci = f"skola_izo_{i}"
        cn = f"obor_nazev_{i}"
        if ci in df_in.columns and cn in df_in.columns:
            is_nase = df_in[ci].astype(str).str.strip() == NASE_SKOLA_IZO
            is_obor = df_in[cn] == obor
            mask = mask | (is_nase & is_obor)
    return df_in[mask]


# =============================================================================
# Souřadnice českých měst pro mapu spádovosti
# =============================================================================

CZECH_CITIES_COORDS: dict[str, tuple[float, float]] = {
    # Praha – čtvrti (formát "Praha-Xxx" jak je v datech)
    "Praha-Chodov": (50.031, 14.505), "Praha-Žižkov": (50.083, 14.450),
    "Praha-Bubeneč": (50.103, 14.400), "Praha-Holešovice": (50.107, 14.438),
    "Praha-Nusle": (50.064, 14.437), "Praha-Stodůlky": (50.048, 14.319),
    "Praha-Kunratice": (50.013, 14.486), "Praha-Dejvice": (50.100, 14.390),
    "Praha-Klánovice": (50.087, 14.614), "Praha-Braník": (50.037, 14.418),
    "Praha-Libuš": (50.013, 14.455), "Praha-Strašnice": (50.072, 14.487),
    "Praha-Vinohrady": (50.075, 14.447), "Praha-Břevnov": (50.083, 14.370),
    "Praha-Čakovice": (50.147, 14.512), "Praha-Malešice": (50.083, 14.498),
    "Praha-Košíře": (50.065, 14.383), "Praha-Libeň": (50.107, 14.473),
    "Praha-Podolí": (50.055, 14.426), "Praha-Jinonice": (50.056, 14.358),
    "Praha-Prosek": (50.117, 14.495), "Praha-Nové Město": (50.078, 14.424),
    "Praha-Horní Měcholupy": (50.058, 14.543), "Praha-Karlín": (50.092, 14.455),
    "Praha-Bohnice": (50.128, 14.414), "Praha-Staré Město": (50.088, 14.420),
    "Praha-Hloubětín": (50.098, 14.520), "Praha-Hostivař": (50.052, 14.524),
    "Praha-Petrovice": (50.030, 14.556), "Praha-Letňany": (50.129, 14.520),
    "Praha-Střížkov": (50.127, 14.492), "Praha-Vysočany": (50.105, 14.497),
    "Praha-Horní Počernice": (50.112, 14.593), "Praha-Kobylisy": (50.124, 14.444),
    "Praha-Modřany": (50.007, 14.408), "Praha-Smíchov": (50.069, 14.402),
    "Praha-Lysolaje": (50.122, 14.374), "Praha-Háje": (50.025, 14.520),
    "Praha-Záběhlice": (50.053, 14.491), "Praha-Vokovice": (50.097, 14.348),
    "Praha-Michle": (50.053, 14.450), "Praha-Satalice": (50.124, 14.553),
    "Praha-Kbely": (50.131, 14.537), "Praha-Troja": (50.118, 14.418),
    "Praha-Dubeč": (50.057, 14.585), "Praha-Krč": (50.038, 14.443),
    "Praha-Nebušice": (50.112, 14.345), "Praha-Kyje": (50.087, 14.533),
    "Praha-Suchdol": (50.140, 14.382), "Praha-Zbraslav": (49.975, 14.388),
    "Praha-Hodkovičky": (50.030, 14.420), "Praha-Malá Strana": (50.087, 14.404),
    "Praha-Slivenec": (50.027, 14.359), "Praha-Hlubočepy": (50.044, 14.388),
    "Praha-Veleslavín": (50.089, 14.342), "Praha-Újezd nad Lesy": (50.078, 14.609),
    "Praha-Vršovice": (50.067, 14.460), "Praha-Vyšehrad": (50.063, 14.420),
    # Středočeský kraj – větší města
    "Benešov": (49.782, 14.687), "Beroun": (49.964, 14.072),
    "Brandýs nad Labem": (50.187, 14.660), "Čáslav": (49.911, 15.390),
    "Černošice": (49.958, 14.322), "Český Brod": (50.075, 14.860),
    "Dobříš": (49.781, 14.167), "Hořovice": (49.836, 13.902),
    "Kladno": (50.147, 14.105), "Kolín": (50.028, 15.200),
    "Kralupy nad Vltavou": (50.241, 14.311), "Kutná Hora": (49.948, 15.268),
    "Lysá nad Labem": (50.201, 14.833), "Mělník": (50.350, 14.474),
    "Mladá Boleslav": (50.411, 14.906), "Mnichovo Hradiště": (50.526, 15.009),
    "Neratovice": (50.260, 14.517), "Nymburk": (50.186, 15.041),
    "Poděbrady": (50.143, 15.119), "Příbram": (49.689, 14.010),
    "Rakovník": (50.106, 13.733), "Říčany": (49.991, 14.654),
    "Sedlčany": (49.661, 14.427), "Slaný": (50.231, 14.087),
    "Vlašim": (49.706, 14.897), "Votice": (49.636, 14.639),
    "Roztoky": (50.158, 14.397), "Hostivice": (50.081, 14.258),
    "Jesenice": (49.969, 14.513), "Průhonice": (50.002, 14.554),
    "Vestec": (49.993, 14.505), "Psáry": (49.941, 14.513),
    "Mníšek pod Brdy": (49.869, 14.263), "Všenory": (49.937, 14.364),
    "Rudná": (50.009, 14.234), "Řevnice": (49.920, 14.231),
    "Davle": (49.881, 14.401), "Štěchovice": (49.854, 14.412),
    "Jílové u Prahy": (49.895, 14.493), "Dolní Břežany": (49.962, 14.458),
    # Středočeský kraj – menší obce kolem Prahy
    "Ondřejov": (49.906, 14.783), "Kamenice": (49.902, 14.583),
    "Čerčany": (49.846, 14.701), "Líbeznice": (50.178, 14.495),
    "Čelákovice": (50.161, 14.753), "Buštěhrad": (50.156, 14.186),
    "Mnichovice": (49.934, 14.710), "Kostelec nad Labem": (50.231, 14.585),
    "Úvaly": (50.073, 14.730), "Veltrusy": (50.274, 14.324),
    "Hradištko": (49.864, 14.417), "Odolena Voda": (50.234, 14.411),
    "Světice": (49.972, 14.658), "Liteň": (49.896, 14.149),
    "Benátky nad Jizerou": (50.291, 14.822), "Kouřim": (50.003, 14.979),
    "Horoměřice": (50.128, 14.348), "Nový Knín": (49.787, 14.190),
    "Středokluky": (50.104, 14.230), "Šestajovice": (50.103, 14.621),
    "Veleň": (50.193, 14.498), "Stříbrná Skalice": (49.914, 14.850),
    "Zeleneč": (50.135, 14.649), "Jirny": (50.103, 14.699),
    "Kostelec nad Černými lesy": (49.994, 14.859), "Pečky": (50.091, 15.024),
    "Milovice": (50.227, 14.887), "Dobřichovice": (49.927, 14.280),
    "Kounice": (50.117, 14.849), "Broumy": (49.870, 13.902),
    "Telecí": (49.670, 16.101), "Polná": (49.488, 15.719),
    "Lázně Bohdaneč": (50.078, 15.679), "Ledeč nad Sázavou": (49.693, 15.278),
    # Jihočeský kraj
    "České Budějovice": (48.975, 14.474), "Český Krumlov": (48.811, 14.315),
    "Jindřichův Hradec": (49.144, 15.003), "Písek": (49.308, 14.148),
    "Prachatice": (49.013, 13.997), "Strakonice": (49.261, 13.902),
    "Tábor": (49.414, 14.678),
    # Plzeňský kraj
    "Plzeň": (49.738, 13.373), "Domažlice": (49.440, 12.929),
    "Klatovy": (49.396, 13.295), "Rokycany": (49.743, 13.595),
    # Karlovarský kraj
    "Karlovy Vary": (50.230, 12.872), "Cheb": (50.080, 12.370),
    "Sokolov": (50.181, 12.640), "Mariánské Lázně": (49.965, 12.701),
    # Ústecký kraj
    "Ústí nad Labem": (50.661, 14.053), "Děčín": (50.773, 14.210),
    "Chomutov": (50.460, 13.414), "Litoměřice": (50.534, 14.132),
    "Louny": (50.357, 13.796), "Most": (50.503, 13.636),
    "Teplice": (50.640, 13.825),
    # Liberecký kraj
    "Liberec": (50.767, 15.056), "Česká Lípa": (50.686, 14.537),
    "Jablonec nad Nisou": (50.728, 15.170), "Turnov": (50.587, 15.153),
    # Královéhradecký kraj
    "Hradec Králové": (50.209, 15.833), "Jičín": (50.437, 15.351),
    "Náchod": (50.417, 16.163), "Trutnov": (50.561, 15.913),
    # Pardubický kraj
    "Pardubice": (50.034, 15.776), "Chrudim": (49.951, 15.795),
    "Svitavy": (49.756, 16.468), "Ústí nad Orlicí": (49.974, 16.393),
    # Kraj Vysočina
    "Jihlava": (49.396, 15.590), "Havlíčkův Brod": (49.607, 15.581),
    "Pelhřimov": (49.431, 15.223), "Třebíč": (49.215, 15.882),
    "Žďár nad Sázavou": (49.563, 15.939),
    # Jihomoravský kraj
    "Brno": (49.195, 16.607), "Blansko": (49.363, 16.644),
    "Břeclav": (48.759, 16.882), "Hodonín": (48.849, 17.132),
    "Vyškov": (49.278, 16.999), "Znojmo": (48.856, 16.049),
    # Olomoucký kraj
    "Olomouc": (49.594, 17.251), "Prostějov": (49.472, 17.111),
    "Přerov": (49.456, 17.451), "Šumperk": (49.966, 16.970),
    # Zlínský kraj
    "Zlín": (49.227, 17.667), "Kroměříž": (49.298, 17.393),
    "Uherské Hradiště": (49.070, 17.460), "Vsetín": (49.339, 17.996),
    # Moravskoslezský kraj
    "Ostrava": (49.821, 18.263), "Frýdek-Místek": (49.688, 18.348),
    "Havířov": (49.780, 18.430), "Karviná": (49.854, 18.542),
    "Nový Jičín": (49.594, 18.010), "Opava": (49.938, 17.905),
    "Třinec": (49.678, 18.670), "Kopřivnice": (49.599, 18.145),
}

# Seřadit názvy sestupně podle délky (aby "Praha-Chodov" matchnul před "Praha")
_MESTA_SORTED = sorted(CZECH_CITIES_COORDS.keys(), key=len, reverse=True)


import re

# Regex pro extrakci města z adresy: "... PSČ Město" (fallback)
_PSC_MESTO_RE = re.compile(r"\b(\d{3})\s*(\d{2})\s+([A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ][a-záčďéěíňóřšťúůýž]+(?:\s+(?:nad|pod|u)\s+[A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ][a-záčďéěíňóřšťúůýž]+)?)")


def extrahuj_mesto(nazev_skoly: str) -> str | None:
    """Extrahuje název města/čtvrti z názvu školy."""
    if not nazev_skoly or pd.isna(nazev_skoly):
        return None
    nazev = str(nazev_skoly)
    nazev_lower = nazev.lower()
    # 1. Zkusit přesný match ze slovníku (nejdelší shoda první)
    for mesto in _MESTA_SORTED:
        if mesto.lower() in nazev_lower:
            return mesto
    # 2. Fallback: parsovat město z PSČ v adrese
    m = _PSC_MESTO_RE.search(nazev)
    if m:
        return m.group(3).split("-")[0].strip()
    return None


# =============================================================================
# Sidebar
# =============================================================================

with st.sidebar:
    st.title("🎓 " + NASE_SKOLA_NAZEV)
    st.caption(f"IZO: {NASE_SKOLA_IZO}")
    st.divider()

    # Globální filtr – obor na naší škole
    vsechny_nase_obory = nase_obory_z_dat(df_full)
    vybrany_obor = st.selectbox(
        "Filtr – obor na naší škole:",
        ["Celkem"] + vsechny_nase_obory,
        key="global_obor",
    )

    st.divider()

# Aplikovat globální filtr
df = filtruj_podle_oboru(df_full, vybrany_obor)

# Spočítat metriky (po filtraci)
pocty_priorit = {}
for p in range(1, 4):
    col = f"skola_izo_{p}"
    if col in df.columns:
        pocty_priorit[p] = int((df[col].astype(str).str.strip() == NASE_SKOLA_IZO).sum())
    else:
        pocty_priorit[p] = 0

# Metriky v sidebaru
with st.sidebar:
    if vybrany_obor != "Celkem":
        st.caption(f"Filtrováno: **{vybrany_obor}**")
    st.metric("Uchazečů (filtr)", len(df))
    for p in range(1, 4):
        st.metric(f"Priorita {p}", pocty_priorit[p])

# Barvy oborů podle webu spgsfuturum.cz
OBOR_BARVY = {
    "Pedagogické lyceum": "rgb(240, 217, 111)",       # žlutá/zlatá
    "Předškolní a mimoškolní pedagogika": "rgb(188, 61, 86)",  # burgundy
    "Lyceum": "rgb(99, 169, 187)",                     # teal
    "Gymnázium": "rgb(0, 72, 127)",                    # tmavě modrá
}
_OBOR_DEFAULT_COLOR = "rgb(160, 160, 160)"  # šedá pro ostatní


def _obor_color(nazev: str) -> str:
    """Vrátí barvu oboru podle webu Futurum."""
    for klic, barva in OBOR_BARVY.items():
        if klic.lower() in nazev.lower():
            return barva
    return _OBOR_DEFAULT_COLOR


# =============================================================================
# Záložky
# =============================================================================

tab_prehled, tab_konkurence, tab_tok, tab_nejsilnejsi, tab_spadovost, tab_prihlasky, tab_obory = st.tabs(
    ["Přehled", "Konkurence", "Tok uchazečů", "Nejsilnější konkurenti", "Spádovost", "Přihlášky", "Obory"]
)

# ─── TAB 1: Přehled ─────────────────────────────────────────────────────────

with tab_prehled:
    st.header("Přehled přihlášek")

    # Metriky v řadě
    cols = st.columns(4)
    cols[0].metric("Celkem uchazečů", len(df))
    for p in range(1, 4):
        cols[p].metric(f"Priorita {p}", pocty_priorit[p])

    st.divider()

    col_left, col_right = st.columns(2)

    # Graf – distribuce priorit
    with col_left:
        st.subheader("Naše škola podle priority")
        chart_data = pd.DataFrame({
            "Priorita": [f"Priorita {p}" for p in range(1, 4)],
            "Počet uchazečů": [pocty_priorit[p] for p in range(1, 4)],
        })
        st.bar_chart(chart_data, x="Priorita", y="Počet uchazečů")

    # Graf – top obory
    with col_right:
        st.subheader("Top 10 oborů (všechny priority)")
        obory_all = []
        for i in range(1, MAX_PRIORIT + 1):
            cn = f"obor_nazev_{i}"
            if cn in df.columns:
                vals = df[cn].dropna()
                vals = vals[vals != ""]
                obory_all.extend(vals.tolist())
        if obory_all:
            obory_counts = pd.Series(obory_all).value_counts().head(10).reset_index()
            obory_counts.columns = ["Obor", "Počet"]
            st.bar_chart(obory_counts, x="Obor", y="Počet")

    # Odkud přicházejí uchazeči – ZŠ / SŠ
    st.divider()
    st.subheader("Odkud přicházejí uchazeči")

    # Uchazeči, kteří mají naši školu kdekoliv v přihláškách
    nasi = df[
        (df[[f"skola_izo_{i}" for i in range(1, MAX_PRIORIT + 1) if f"skola_izo_{i}" in df.columns]]
         .astype(str)
         .apply(lambda row: row.str.strip().eq(NASE_SKOLA_IZO).any(), axis=1))
    ]

    typ_skoly = st.radio(
        "Typ školy:",
        ["Základní školy", "Střední školy"],
        horizontal=True,
        key="odkud_typ",
    )

    sloupec = "zakladni_skola" if typ_skoly == "Základní školy" else "stredni_skola"

    if sloupec in nasi.columns:
        zdroj = nasi[sloupec].dropna()
        zdroj = zdroj[zdroj.str.strip() != ""]
        if len(zdroj) > 0:
            zdroj_counts_all = zdroj.value_counts().reset_index()
            zdroj_counts_all.columns = ["Škola", "Počet"]
            zdroj_counts = zdroj_counts_all.head(20)
            st.caption(f"Zobrazeno top {len(zdroj_counts)} z {zdroj.nunique()} unikátních škol")
            st.dataframe(zdroj_counts, use_container_width=True, hide_index=True)
            st.download_button(
                "⬇️ Stáhnout celý seznam (CSV)",
                data=zdroj_counts_all.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"odkud_prichazeji_{sloupec}.csv",
                mime="text/csv",
                key=f"dl_odkud_{sloupec}",
            )
        else:
            st.info(f"Žádné záznamy pro sloupec {sloupec}.")
    else:
        st.warning(f"Sloupec '{sloupec}' není v datech.")

# ─── TAB 2: Konkurence ──────────────────────────────────────────────────────

with tab_konkurence:
    st.header("Analýza konkurence")

    volba_priority = st.radio(
        "Naše škola je uvedena jako:",
        ["Celkem", "Priorita 1", "Priorita 2", "Priorita 3"],
        horizontal=True,
    )

    priorita = None if volba_priority == "Celkem" else int(volba_priority[-1])
    skoly, skoly_obory, pocet = get_konkurence(df, priorita, cs_msmt, cs_csv)

    popis = f"na **prioritě {priorita}**" if priorita else "na **jakékoliv prioritě**"
    st.info(f"**{pocet}** uchazečů má {NASE_SKOLA_NAZEV} {popis}")

    if skoly is not None and len(skoly) > 0:
        col1, col2 = st.columns([1, 1])

        with col1:
            st.subheader("Konkurenční školy")
            _skoly_export = skoly.rename(columns={"nazev_skoly": "Škola", "pocet": "Počet uchazečů"})
            st.dataframe(
                _skoly_export,
                use_container_width=True,
                hide_index=True,
                height=500,
            )
            st.download_button(
                "⬇️ Stáhnout celý seznam (CSV)",
                data=_skoly_export.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"konkurencni_skoly_{volba_priority.lower().replace(' ', '_')}.csv",
                mime="text/csv",
                key=f"dl_konk_skoly_{volba_priority}",
            )

        with col2:
            st.subheader(f"Top {min(15, len(skoly))} konkurentů")
            chart = skoly.head(15).copy()
            # Zkrátit dlouhé názvy pro graf
            chart["label"] = chart["nazev_skoly"].apply(
                lambda x: (x[:40] + "...") if len(x) > 43 else x
            )
            st.bar_chart(chart, x="label", y="pocet")

        st.divider()
        st.subheader("Detail: školy + obory")
        if skoly_obory is not None:
            _skoly_obory_export = skoly_obory.rename(columns={
                "nazev_skoly": "Škola",
                "kod_oboru": "Kód oboru",
                "nazev_oboru": "Obor",
                "pocet": "Počet",
            })
            st.dataframe(
                _skoly_obory_export,
                use_container_width=True,
                hide_index=True,
                height=500,
            )
            st.download_button(
                "⬇️ Stáhnout celý seznam (CSV)",
                data=_skoly_obory_export.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"konkurencni_skoly_obory_{volba_priority.lower().replace(' ', '_')}.csv",
                mime="text/csv",
                key=f"dl_konk_skoly_obory_{volba_priority}",
            )
    else:
        st.warning("Žádné konkurenční přihlášky nalezeny.")

# ─── TAB 3: Tok uchazečů (Sankey) ──────────────────────────────────────────

with tab_tok:
    st.header("Tok uchazečů mezi školami")
    st.caption("Jak se uchazeči distribuují mezi školami na prioritách 1 → 2 → 3")

    # Najít uchazeče s Futurem kdekoliv v P1-P3
    _izo_cols_sankey = [f"skola_izo_{i}" for i in range(1, 4) if f"skola_izo_{i}" in df.columns]
    _mask_sankey = df[_izo_cols_sankey].astype(str).apply(
        lambda row: row.str.strip().eq(NASE_SKOLA_IZO).any(), axis=1
    )
    _nasi_sankey = df[_mask_sankey].copy()

    if len(_nasi_sankey) == 0:
        st.warning("Žádní uchazeči s naší školou.")
    else:
        sankey_top_n = st.slider("Počet zobrazených konkurentů:", 5, 20, 10, key="sankey_top")

        # Přiřadit názvy škol pro P1-P3
        for _i in range(1, 4):
            _col_izo = f"skola_izo_{_i}"
            if _col_izo in _nasi_sankey.columns:
                _nasi_sankey[f"skola_p{_i}"] = _nasi_sankey[_col_izo].apply(
                    lambda x: NASE_SKOLA_NAZEV if str(x).strip() == NASE_SKOLA_IZO
                    else (preloz_izo(str(x).strip(), cs_msmt, cs_csv)
                          if str(x).strip() and str(x).strip() != "nan" else "Nevyplněno")
                )
            else:
                _nasi_sankey[f"skola_p{_i}"] = "Nevyplněno"

        # Určit top školy
        _all_s = []
        for _i in range(1, 4):
            _all_s.extend(_nasi_sankey[f"skola_p{_i}"].tolist())
        _s_counts = Counter(s for s in _all_s if s not in (NASE_SKOLA_NAZEV, "Nevyplněno", ""))
        _top_set = {NASE_SKOLA_NAZEV}
        for _s, _ in _s_counts.most_common(sankey_top_n):
            _top_set.add(_s)

        # Seskupit menší školy jako "Ostatní"
        for _i in range(1, 4):
            _nasi_sankey[f"skola_p{_i}_g"] = _nasi_sankey[f"skola_p{_i}"].apply(
                lambda x: x if x in _top_set or x == "Nevyplněno" else "Ostatní školy"
            )

        # Sestavit uzly a linky Sankey diagramu
        _nodes = {}
        _node_labels = []
        _node_colors = []

        def _get_node_id(priority: int, school: str) -> int:
            key = f"P{priority}:{school}"
            if key not in _nodes:
                _nodes[key] = len(_nodes)
                _node_labels.append(school)
                if school == NASE_SKOLA_NAZEV:
                    _node_colors.append("rgba(46, 134, 193, 0.8)")
                elif school == "Ostatní školy":
                    _node_colors.append("rgba(180, 180, 180, 0.6)")
                elif school == "Nevyplněno":
                    _node_colors.append("rgba(220, 220, 220, 0.4)")
                else:
                    _node_colors.append("rgba(231, 76, 60, 0.7)")
            return _nodes[key]

        _sources, _targets, _values, _link_colors = [], [], [], []

        for _from_p, _to_p in [(1, 2), (2, 3)]:
            _combos = (
                _nasi_sankey.groupby([f"skola_p{_from_p}_g", f"skola_p{_to_p}_g"])
                .size()
                .reset_index(name="count")
            )
            for _, _row in _combos.iterrows():
                _src_name = _row[f"skola_p{_from_p}_g"]
                _tgt_name = _row[f"skola_p{_to_p}_g"]
                # Přeskočit "Nevyplněno" linky
                if _src_name == "Nevyplněno" or _tgt_name == "Nevyplněno":
                    continue
                _src = _get_node_id(_from_p, _src_name)
                _tgt = _get_node_id(_to_p, _tgt_name)
                _sources.append(_src)
                _targets.append(_tgt)
                _values.append(int(_row["count"]))
                if _src_name == NASE_SKOLA_NAZEV:
                    _link_colors.append("rgba(46, 134, 193, 0.3)")
                elif _tgt_name == NASE_SKOLA_NAZEV:
                    _link_colors.append("rgba(46, 134, 193, 0.2)")
                else:
                    _link_colors.append("rgba(200, 200, 200, 0.2)")

        if _sources:
            _fig_sankey = go.Figure(go.Sankey(
                node=dict(
                    pad=15,
                    thickness=20,
                    line=dict(color="black", width=0.5),
                    label=_node_labels,
                    color=_node_colors,
                ),
                link=dict(
                    source=_sources,
                    target=_targets,
                    value=_values,
                    color=_link_colors,
                ),
            ))
            _fig_sankey.update_layout(
                font_size=12,
                height=650,
                margin=dict(l=10, r=10, t=40, b=10),
                annotations=[
                    dict(x=0, y=1.08, text="Priorita 1", showarrow=False,
                         font=dict(size=14, color="gray"), xref="paper", yref="paper"),
                    dict(x=0.5, y=1.08, text="Priorita 2", showarrow=False,
                         font=dict(size=14, color="gray"), xref="paper", yref="paper"),
                    dict(x=1, y=1.08, text="Priorita 3", showarrow=False,
                         font=dict(size=14, color="gray"), xref="paper", yref="paper"),
                ],
            )
            st.plotly_chart(_fig_sankey, use_container_width=True)
        else:
            st.info("Nedostatek dat pro zobrazení Sankey diagramu.")

# ─── TAB 4: Překryv škol (heatmapa) ───────────────────────────────────────

# Brand kódy konkurentů (ručně sestavené)
KONKURENT_BRAND: dict[str, dict] = {
    "Vyšší odborná škola pedagogická a sociální, Střední odborná škola pedagogická a Gymnázium, Praha 6, Evropská 33": {
        "zkratka": "PED Evropská 33",
        "web": "https://www.pedevropska.cz/",
        "barva_primary": "#BA2727",
        "barva_secondary": "#2F2412",
        "barvy_popis": "Burgundy / vínová + tmavě šedá",
        "ton": "Formální, tradiční, akademický. Odkazuje na Komenského, důraz na humanitní tradici.",
        "instagram": "https://www.instagram.com/pedevropska/",
        "facebook": "https://www.facebook.com/pedevropska/",
        "linkedin": None,
        "youtube": None,
        "typ": "Veřejná",
    },
    "Gymnázium FOSTRA International s.r.o.": {
        "zkratka": "FOSTRA International",
        "web": "https://www.fostra.cz/",
        "barva_primary": "#1565C0",
        "barva_secondary": "#F5F5F5",
        "barvy_popis": "Modrá + světle šedá, moderní čistý design",
        "ton": "Přátelský a profesionální. Inspirativní, zaměřený na osobní rozvoj a 21. století.",
        "instagram": "https://www.instagram.com/gymnazium_fostra/",
        "facebook": "https://www.facebook.com/SkolyFostra",
        "linkedin": "https://www.linkedin.com/company/fostra-praha",
        "youtube": "https://www.youtube.com/@skoly.fostra",
        "typ": "Soukromá",
    },
    "Klinická univerzitní škola EduVia, gymnázium a SŠ pedagogická": {
        "zkratka": "EduVia (UK PedF)",
        "web": "https://eduvia.pedf.cuni.cz/",
        "barva_primary": "#23B5B5",
        "barva_secondary": "#EC662C",
        "barvy_popis": "Teal/tyrkys + korálová, moderní akademický styl",
        "ton": "Inspirativní, akademicky podložený. Škola 21. století, propojení s Univerzitou Karlovou.",
        "instagram": "https://www.instagram.com/eduvia_pedf_uk/",
        "facebook": "https://www.facebook.com/profile.php?id=61583764203108",
        "linkedin": None,
        "youtube": None,
        "typ": "Veřejná (UK PedF)",
    },
    "Evangelická akademie - pedagogické lyceum a střední odborná škola": {
        "zkratka": "Evangelická akademie",
        "web": "https://www.eapraha.cz/",
        "barva_primary": "#09B474",
        "barva_secondary": "#333333",
        "barvy_popis": "Zelená + tmavě šedá, minimalistický design",
        "ton": "Formální, ale vřelý. Komunitní, hodnotově orientovaný, inkluzivní.",
        "instagram": "https://www.instagram.com/ea_praha/",
        "facebook": "https://www.facebook.com/EAPRAHA/",
        "linkedin": None,
        "youtube": "https://www.youtube.com/@evangelickaakademie",
        "typ": "Církevní",
    },
    "Gymnázium KUDYKAMPUS International s.r.o.": {
        "zkratka": "KUDYKAMPUS",
        "web": "https://www.gymnaziumkudykampus.cz/",
        "barva_primary": "#FFC425",
        "barva_secondary": "#17575B",
        "barvy_popis": "Žlutá + teal, hravý a energický design",
        "ton": "Neformální, hravý, konverzační. Cílí na mladé, motivační jazyk, studentské hlasy.",
        "instagram": "https://www.instagram.com/gymnazium.kudykampus/",
        "facebook": "https://www.facebook.com/profile.php?id=100090476734642",
        "linkedin": None,
        "youtube": None,
        "typ": "Soukromá",
    },
    "GYMNÁZIUM JANA PALACHA PRAHA 1, s.r.o.": {
        "zkratka": "GJP1",
        "web": "https://www.gjp1.cz/",
        "barva_primary": "#FBD109",
        "barva_secondary": "#1A1A2E",
        "barvy_popis": "Žlutá + tmavě modrá/černá, energický moderní design",
        "ton": "Moderní, přístupný a sebevědomý. Slogan 'Učíme jinak' signalizuje inovativnost. Progresivní soukromé gymnázium s tradicí od 1991.",
        "instagram": "https://www.instagram.com/gymjanapalacha1/",
        "facebook": "https://www.facebook.com/GJP1Praha/",
        "linkedin": "https://cz.linkedin.com/company/gymnázium-jana-palacha-praha-1-s-r-o",
        "youtube": "https://www.youtube.com/channel/UCchFlodRPmXf-oOHuB5YEpw",
        "typ": "Soukromá",
    },
    "ScioŠkola Žižkov - střední škola, s.r.o.": {
        "zkratka": "ScioŠkola Žižkov",
        "web": "https://zizkov-stredni.scioskola.cz/",
        "barva_primary": "#009BDE",
        "barva_secondary": "#FFC107",
        "barvy_popis": "Modrá + žlutá, progresivní a svěží",
        "ton": "Progresivní, studentocentrický. Důraz na svobodu, odpovědnost a vnitřní motivaci. Partnerský jazyk, škola jako průvodce.",
        "instagram": "https://www.instagram.com/stredniscioskola/",
        "facebook": "https://www.facebook.com/stredniscioskola",
        "linkedin": "https://cz.linkedin.com/company/scioskoly",
        "youtube": None,
        "typ": "Soukromá",
    },
    "ART ECON - Gymnázium a Střední odborná škola Praha, s.r.o.": {
        "zkratka": "ART ECON",
        "web": "https://artecon.cz/praha/",
        "barva_primary": "#A83D72",
        "barva_secondary": "#000000",
        "barvy_popis": "Magenta/berry + černá, minimalistický designový styl",
        "ton": "Moderní, stručný a sebejistý. 'Škola plná talentu.' Propojení umění, ekonomiky a gymnázia. Fakultní škola UK, 30 let tradice.",
        "instagram": "https://www.instagram.com/arteconpraha/",
        "facebook": "https://www.facebook.com/arteconrokoska/",
        "linkedin": None,
        "youtube": None,
        "typ": "Soukromá",
    },
    "Střední škola gastronomická a hotelová s.r.o.": {
        "zkratka": "SSGH",
        "web": "https://www.ssgh.cz/",
        "barva_primary": "#32373C",
        "barva_secondary": "#FFFFFF",
        "barvy_popis": "Tmavě šedá + bílá, neutrální profesionální paleta",
        "ton": "Profesionální a prakticky orientovaný. Kariérní příprava, zahraniční stáže (Čína, USA, Kanada). Cambridge English centrum.",
        "instagram": "https://www.instagram.com/ssgh.cz/",
        "facebook": "https://www.facebook.com/ssghpraha4",
        "linkedin": "https://www.linkedin.com/organization/15232021",
        "youtube": "https://www.youtube.com/c/Středníškolagastronomickáahotelová",
        "typ": "Soukromá",
    },
    "MICHAEL - Střední škola, Gymnázium a Vyšší odborná škola, s.r.o.": {
        "zkratka": "MICHAEL",
        "web": "https://www.skolamichael.cz/",
        "barva_primary": "#EF6C74",
        "barva_secondary": "#373737",
        "barvy_popis": "Korálová/lososová + tmavě šedá, kreativní moderní styl",
        "ton": "Aspirační a kreativní. 'Vysněná budoucnost začíná na škole Michael.' 80 % praxe / 20 % teorie. Reklama, design, foto, film, game design.",
        "instagram": "https://www.instagram.com/skola_michael/",
        "facebook": "https://www.facebook.com/skolamichael",
        "linkedin": "https://cz.linkedin.com/company/skolamichael",
        "youtube": "https://www.youtube.com/channel/UC8Z3uhpMKcr5MVjp4T_RQew",
        "typ": "Soukromá",
    },
}

FUTURUM_BRAND = {
    "zkratka": "Futurum",
    "web": "https://spgsfuturum.cz/",
    "ton": "Moderní, osobní a komunitní. Důraz na pedagogiku, lidský přístup a přípravu pro praxi.",
    "instagram": "https://www.instagram.com/spgs_futurum/",
    "facebook": "https://web.facebook.com/SpgsFuturumPraha",
    "linkedin": None,
    "youtube": "https://www.youtube.com/@spgsfuturum4594",
    "typ": "Soukromá",
    "obory": [
        "Pedagogické lyceum",
        "Předškolní a mimoškolní pedagogika",
        "Lyceum v oboru humanitních a společenských věd",
        "Gymnázium",
    ],
}


def generuj_smart_shrnuti(
    nazev: str, kd: dict, brand: dict | None, celkem: int,
) -> dict[str, str]:
    """Vygeneruje rule-based smart shrnutí pro daného konkurenta."""
    pocet = kd["pocet"]
    podil = pocet / celkem * 100 if celkem else 0
    p_nas = kd["priority_nas"]
    p_kon = kd["priority_kon"]
    avg_nas = sum(p_nas) / len(p_nas) if p_nas else 0
    avg_kon = sum(p_kon) / len(p_kon) if p_kon else 0
    win = kd["za_nami"]
    lose = kd["pred_nami"]
    win_rate = win / pocet * 100 if pocet else 0
    lose_rate = lose / pocet * 100 if pocet else 0

    # --- 1. Konkurenční pozice ---
    lines_pos = []
    if podil > 30:
        lines_pos.append(f"Klíčový konkurent -- sdílíme **{podil:.0f} %** našich uchazečů ({pocet} z {celkem}).")
    elif podil > 15:
        lines_pos.append(f"Středně silná konkurence -- sdílíme **{podil:.0f} %** uchazečů ({pocet}).")
    else:
        lines_pos.append(f"Menší překryv -- sdílíme **{podil:.0f} %** uchazečů ({pocet}).")

    if win_rate > 60:
        lines_pos.append(f"Futurum je jasně preferované: **{win_rate:.0f} %** uchazečů nás řadí výš.")
    elif win_rate > 50:
        lines_pos.append(f"Mírná převaha Futura: **{win_rate:.0f} %** uchazečů nás preferuje.")
    elif lose_rate > 60:
        lines_pos.append(f"Konkurent je silnější volbou: **{lose_rate:.0f} %** uchazečů ho řadí výš než nás.")
    elif lose_rate > 50:
        lines_pos.append(f"Konkurent má mírnou převahu v preferencích ({lose_rate:.0f} %).")
    else:
        lines_pos.append("Uchazeči vnímají obě školy vyrovnaně.")

    if avg_nas and avg_kon:
        if avg_nas < avg_kon:
            lines_pos.append(
                f"Naše průměrná priorita **{avg_nas:.1f}** vs. konkurentova **{avg_kon:.1f}** -- uchazeči nás typicky řadí výš."
            )
        elif avg_kon < avg_nas:
            lines_pos.append(
                f"Konkurentova průměrná priorita **{avg_kon:.1f}** vs. naše **{avg_nas:.1f}** -- uchazeči preferují konkurenta."
            )

    # --- 2. Komunikace a brand ---
    lines_kom = []
    if brand:
        ton = brand.get("ton", "").lower()
        typ = brand.get("typ", "")

        if "neformální" in ton or "hravý" in ton or "konverzační" in ton:
            lines_kom.append("Konkurent sází na neformální hravý styl. Futurum může zdůraznit profesionalitu, pedagogickou odbornost a stabilitu.")
        elif "formální" in ton and ("vřelý" in ton or "komunitní" in ton):
            lines_kom.append("Konkurent kombinuje formální přístup s komunitním duchem. Futurum se může odlišit modernějším tónem a důrazem na inovace ve vzdělávání.")
        elif "formální" in ton or "tradiční" in ton:
            lines_kom.append("Konkurent komunikuje formálně a tradičně. Futurum se může odlišit modernějším, osobnějším tónem a důrazem na komunitu.")
        elif "kreativní" in ton or "aspirační" in ton:
            lines_kom.append("Konkurent cílí na kreativitu a aspirace. Futurum se může odlišit důrazem na pedagogické hodnoty a všestrannou přípravu.")
        elif "progresivní" in ton or "inovativní" in ton or "studentocentr" in ton:
            lines_kom.append("Konkurent se pozicuje jako inovativní. Futurum by mělo zdůraznit praktické výsledky, úspěchy absolventů a silnou komunitu.")
        elif "přátelský" in ton or ("profesionální" in ton and "inspirativ" in ton):
            lines_kom.append("Konkurent komunikuje přátelsky a inspirativně. Futurum může posílit diferenciaci důrazem na pedagogickou tradici, praxi a osobní rozvoj.")
        elif "profesionální" in ton and "praktick" in ton:
            lines_kom.append("Konkurent sází na profesionalitu a praktickou přípravu. Futurum se může odlišit širším humanitním záběrem a důrazem na osobnostní rozvoj.")
        elif "moderní" in ton or "sebejistý" in ton or "sebevědomý" in ton:
            lines_kom.append("Konkurent komunikuje moderně a sebevědomě. Futurum může posílit svůj příběh důrazem na komunitu, hodnoty a individuální přístup ke studentům.")
        elif "inspirativní" in ton or "akademick" in ton:
            lines_kom.append("Konkurent staví na akademické prestiži. Futurum může nabídnout osobní přístup, menší kolektivy a praxi.")
        else:
            lines_kom.append("Komunikační styl konkurenta se liší od Futura. Doporučujeme analyzovat jeho online prezentaci a identifikovat diferenciační příležitosti.")

        if typ == "Veřejná" or "Veřejná" in typ:
            lines_kom.append("Jako soukromá škola může Futurum zdůrazňovat individuální péči, menší kolektivy a flexibilitu oproti veřejné konkurenci.")
        elif typ == "Církevní":
            lines_kom.append("Církevní škola má specifickou hodnotovou komunitu. Futurum může oslovit širší publikum bez hodnotového předvýběru.")
        elif typ == "Soukromá":
            lines_kom.append("Obě školy jsou soukromé -- rozhoduje kvalita programu, značky a studentské zkušenosti.")
    else:
        lines_kom.append("Pro tohoto konkurenta nemáme brandová data.")

    # --- 3. Silné stránky Futura ---
    lines_sil = []
    if win_rate > 50:
        lines_sil.append(f"Uchazeči nás preferují -- {win_rate:.0f} % nás řadí na vyšší prioritu.")
    if avg_nas and avg_nas <= 2.0:
        lines_sil.append(f"Futurum je typicky 1. nebo 2. volba (Ø {avg_nas:.1f}) u uchazečů zvažujících i tuto školu.")

    # oborový překryv
    kon_obory = set(kd["obory"].keys())
    futurum_obory_lower = {o.lower() for o in FUTURUM_BRAND["obory"]}
    overlap = sum(1 for o in kon_obory if any(fo in o.lower() for fo in ["pedagog", "lyceum", "gymnáz", "předškol"]))
    if overlap > 0:
        lines_sil.append("Přímá oborová konkurence -- uchazeči srovnávají podobné programy. Naše unikátní kombinace pedagogických oborů a gymnázia pod jednou střechou je výhodou.")
    else:
        lines_sil.append("Slabá oborová konkurence -- uchazeči u konkurenta hledají jiný profil. Futurum je pro ně alternativní volbou, což znamená příležitost oslovit je naší nabídkou.")

    if not lines_sil:
        lines_sil.append("Futurum nabízí unikátní kombinaci pedagogických oborů a gymnázia pod jednou střechou.")

    # --- 4. Příležitosti k růstu ---
    lines_pril = []
    if lose_rate > 50:
        lines_pril.append(f"**{lose_rate:.0f} %** sdílených uchazečů nás řadí níže -- prostor pro zlepšení positioningu vůči tomuto konkurentovi.")

    # obory u konkurenta, které my nenabízíme
    nase_klicova = {"pedagog", "lyceum", "gymnáz", "předškol", "humanit"}
    cizi_obory = []
    for obor, cnt in kd["obory"].most_common(5):
        obor_l = obor.lower()
        if not any(k in obor_l for k in nase_klicova):
            cizi_obory.append(f"{obor} ({cnt}x)")
    if cizi_obory:
        lines_pril.append(f"Uchazeči konkurenta se hlásí i na obory, které Futurum nenabízí: {', '.join(cizi_obory[:3])}. Potenciál pro cílený marketing nebo rozšíření portfolia.")

    if podil > 20 and lose_rate > 40:
        lines_pril.append("Vysoký počet sdílených uchazečů s nižší preferencí = prostor pro diferenciační kampaň (den otevřených dveří, studentské ambasadory).")

    if avg_kon and avg_kon < 1.5:
        lines_pril.append("Uchazeči řadí konkurenta velmi vysoko -- je třeba aktivně komunikovat výhody Futura již v rané fázi rozhodování.")

    if not lines_pril:
        lines_pril.append("Aktuálně nemáme identifikované výrazné hrozby od tohoto konkurenta.")

    # --- 5. Sociální sítě ---
    lines_soc = []
    if brand:
        futurum_kanaly = {"instagram", "facebook", "linkedin", "youtube"}
        for kanal in futurum_kanaly:
            kon_ma = brand.get(kanal) is not None
            fut_ma = FUTURUM_BRAND.get(kanal) is not None
            kanal_cz = {"instagram": "Instagram", "facebook": "Facebook",
                        "linkedin": "LinkedIn", "youtube": "YouTube"}[kanal]
            if kon_ma and not fut_ma:
                lines_soc.append(f"Konkurent je na **{kanal_cz}**, Futurum ne -- příležitost k rozšíření dosahu.")
            elif fut_ma and not kon_ma:
                lines_soc.append(f"Futurum má výhodu na **{kanal_cz}**, kde konkurent chybí.")

        kon_pocet = sum(1 for k in futurum_kanaly if brand.get(k))
        fut_pocet = sum(1 for k in futurum_kanaly if FUTURUM_BRAND.get(k))
        if kon_pocet > fut_pocet:
            lines_soc.append(f"Konkurent je na {kon_pocet} platformách vs. Futurum na {fut_pocet} -- zvážit rozšíření online přítomnosti.")
        elif fut_pocet > kon_pocet:
            lines_soc.append(f"Futurum pokrývá {fut_pocet} platformy vs. konkurent {kon_pocet} -- širší online dosah je naše výhoda.")
    else:
        lines_soc.append("Pro tohoto konkurenta nemáme data o online prezenci.")

    return {
        "pozice": "\n\n".join(lines_pos),
        "komunikace": "\n\n".join(lines_kom),
        "silne_stranky": "\n\n".join(lines_sil),
        "prilezitosti": "\n\n".join(lines_pril),
        "socialni_site": "\n\n".join(lines_soc),
        "win_rate": win_rate,
    }


with tab_nejsilnejsi:
    st.header("Nejsilnější konkurenti")
    st.caption("Detailní profil škol, se kterými se nejčastěji potkáváme na přihláškách")

    _nk_top_n = st.slider("Počet konkurentů k analýze:", 3, 15, 7, key="nk_top")

    # Sesbírat data o našich uchazečích
    _izo_cols_nk = [f"skola_izo_{i}" for i in range(1, MAX_PRIORIT + 1) if f"skola_izo_{i}" in df.columns]
    _mask_nk = df[_izo_cols_nk].astype(str).apply(
        lambda row: row.str.strip().eq(NASE_SKOLA_IZO).any(), axis=1
    )
    _nasi_nk = df[_mask_nk]
    _celkem_nasich = len(_nasi_nk)

    # Pro každého uchazeče zjistit školy + priority
    _konkurent_data: dict[str, dict] = {}  # název → {pocet, priority_nas, priority_kon, obory}

    for _, _row in _nasi_nk.iterrows():
        # Najít na jaké prioritě je naše škola
        _nasa_priorita = None
        for _i in range(1, MAX_PRIORIT + 1):
            if str(_row.get(f"skola_izo_{_i}", "")).strip() == NASE_SKOLA_IZO:
                _nasa_priorita = _i
                break

        # Projít ostatní školy tohoto uchazeče
        for _i in range(1, MAX_PRIORIT + 1):
            _izo = str(_row.get(f"skola_izo_{_i}", "")).strip()
            _nazev = str(_row.get(f"skola_nazev_{_i}", "")).strip()
            _obor = str(_row.get(f"obor_nazev_{_i}", "")).strip()
            if not _nazev or _nazev == "nan" or _izo == NASE_SKOLA_IZO:
                continue
            if _nazev not in _konkurent_data:
                _konkurent_data[_nazev] = {
                    "pocet": 0,
                    "priority_nas": [],
                    "priority_kon": [],
                    "obory": Counter(),
                    "pred_nami": 0,
                    "za_nami": 0,
                }
            _kd = _konkurent_data[_nazev]
            _kd["pocet"] += 1
            if _nasa_priorita:
                _kd["priority_nas"].append(_nasa_priorita)
            _kd["priority_kon"].append(_i)
            if _obor and _obor != "nan":
                _kd["obory"][_obor] += 1
            if _nasa_priorita and _i < _nasa_priorita:
                _kd["pred_nami"] += 1
            elif _nasa_priorita and _i > _nasa_priorita:
                _kd["za_nami"] += 1

    if not _konkurent_data:
        st.warning("Žádná data o konkurentech.")
    else:
        # Seřadit a vzít top N
        _sorted_konk = sorted(_konkurent_data.items(), key=lambda x: x[1]["pocet"], reverse=True)[:_nk_top_n]

        # --- Souhrnná tabulka ---
        _rows_nk = []
        for _nazev, _d in _sorted_konk:
            _avg_p_kon = sum(_d["priority_kon"]) / len(_d["priority_kon"]) if _d["priority_kon"] else 0
            _avg_p_nas = sum(_d["priority_nas"]) / len(_d["priority_nas"]) if _d["priority_nas"] else 0
            _top_obor = _d["obory"].most_common(1)[0][0] if _d["obory"] else "–"
            _podil = _d["pocet"] / _celkem_nasich * 100 if _celkem_nasich else 0
            _rows_nk.append({
                "Škola": _nazev,
                "Společných uchazečů": _d["pocet"],
                "Podíl z našich (%)": round(_podil, 1),
                "∅ priorita konkurenta": round(_avg_p_kon, 1),
                "∅ naše priorita": round(_avg_p_nas, 1),
                "Výš než my": _d["pred_nami"],
                "Níž než my": _d["za_nami"],
                "Nejčastější obor": _top_obor,
            })
        _df_nk = pd.DataFrame(_rows_nk)

        st.subheader("Srovnávací tabulka")
        st.dataframe(_df_nk, use_container_width=True, hide_index=True)

        # --- Graf: společní uchazeči ---
        st.subheader("Počet společných uchazečů")
        _labels_nk = [n[:40] + "…" if len(n) > 43 else n for n, _ in _sorted_konk]
        _vals_nk = [d["pocet"] for _, d in _sorted_konk]
        _colors_nk = ["rgb(188, 61, 86)" if d["pred_nami"] > d["za_nami"]
                       else "rgb(99, 169, 187)" for _, d in _sorted_konk]

        _fig_nk_bar = go.Figure(go.Bar(
            x=_labels_nk,
            y=_vals_nk,
            marker_color=_colors_nk,
            text=_vals_nk,
            textposition="outside",
        ))
        _fig_nk_bar.update_layout(
            xaxis_title="", yaxis_title="Počet uchazečů",
            showlegend=False, margin=dict(t=20, b=100),
            xaxis_tickangle=-30, plot_bgcolor="white",
        )
        st.plotly_chart(_fig_nk_bar, use_container_width=True)
        st.caption("🔴 Burgundy = konkurent je častěji na vyšší prioritě než my. "
                   "🔵 Teal = my jsme častěji na vyšší prioritě.")

        # --- Graf: priorita konkurentů vs naše ---
        st.subheader("Průměrná priorita: my vs. konkurent")
        _fig_priority = go.Figure()
        _fig_priority.add_trace(go.Bar(
            name="∅ naše priorita",
            x=_labels_nk,
            y=[d["priority_nas"] and round(sum(d["priority_nas"]) / len(d["priority_nas"]), 1)
               for _, d in _sorted_konk],
            marker_color="rgb(0, 72, 127)",
            text=[d["priority_nas"] and round(sum(d["priority_nas"]) / len(d["priority_nas"]), 1)
                  for _, d in _sorted_konk],
            textposition="outside",
        ))
        _fig_priority.add_trace(go.Bar(
            name="∅ priorita konkurenta",
            x=_labels_nk,
            y=[round(sum(d["priority_kon"]) / len(d["priority_kon"]), 1) if d["priority_kon"] else 0
               for _, d in _sorted_konk],
            marker_color="rgb(240, 217, 111)",
            text=[round(sum(d["priority_kon"]) / len(d["priority_kon"]), 1) if d["priority_kon"] else 0
                  for _, d in _sorted_konk],
            textposition="outside",
        ))
        _fig_priority.update_layout(
            barmode="group",
            xaxis_title="", yaxis_title="Průměrná priorita (1 = nejvyšší)",
            margin=dict(t=20, b=100),
            xaxis_tickangle=-30, plot_bgcolor="white",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5),
        )
        st.plotly_chart(_fig_priority, use_container_width=True)
        st.caption("Nižší číslo = vyšší priorita. Pokud má konkurent nižší průměr než my, "
                   "uchazeči ho preferují.")

        # --- Detail konkurenta ---
        st.divider()
        st.subheader("Detail konkurenta")
        _selected_konk = st.selectbox(
            "Vyber konkurenta:",
            [n for n, _ in _sorted_konk],
            key="nk_select",
        )
        if _selected_konk and _selected_konk in _konkurent_data:
            # --- Brand karta ---
            _brand = KONKURENT_BRAND.get(_selected_konk)
            if _brand:
                _c1, _c2 = st.columns([1, 2])
                with _c1:
                    st.markdown(
                        f'<div style="display:flex;gap:8px;align-items:center;margin-bottom:8px">'
                        f'<div style="width:36px;height:36px;border-radius:6px;background:{_brand["barva_primary"]}"></div>'
                        f'<div style="width:36px;height:36px;border-radius:6px;background:{_brand["barva_secondary"]}"></div>'
                        f'<span style="font-size:13px;color:#666">{_brand["barvy_popis"]}</span>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
                    st.markdown(f"**Typ:** {_brand['typ']}")
                    st.markdown(f"**Web:** [{_brand['zkratka']}]({_brand['web']})")
                    _socials = []
                    if _brand.get("instagram"):
                        _socials.append(f"[Instagram]({_brand['instagram']})")
                    if _brand.get("facebook"):
                        _socials.append(f"[Facebook]({_brand['facebook']})")
                    if _brand.get("linkedin"):
                        _socials.append(f"[LinkedIn]({_brand['linkedin']})")
                    if _brand.get("youtube"):
                        _socials.append(f"[YouTube]({_brand['youtube']})")
                    if _socials:
                        st.markdown("**Sítě:** " + " | ".join(_socials))
                with _c2:
                    st.markdown(f"**Tón komunikace:**  \n{_brand['ton']}")

            # --- Obory ---
            _kd_sel = _konkurent_data[_selected_konk]
            _obor_items = _kd_sel["obory"].most_common(10)
            if _obor_items:
                st.markdown("**Obory:**  \n" + "  \n".join(
                    f"- {obor} ({pocet})" for obor, pocet in _obor_items
                ))

            # --- Smart shrnutí ---
            st.divider()
            st.markdown("### Smart shrnutí")

            _shrnuti = generuj_smart_shrnuti(
                _selected_konk, _kd_sel, _brand, _celkem_nasich
            )

            # Gauge chart - preferenční skóre
            _wr = _shrnuti["win_rate"]
            _fig_gauge = go.Figure(go.Indicator(
                mode="gauge+number",
                value=round(_wr, 1),
                number={"suffix": " %"},
                title={"text": "Preferenční skóre Futura"},
                gauge={
                    "axis": {"range": [0, 100]},
                    "bar": {"color": "rgb(0, 72, 127)"},
                    "steps": [
                        {"range": [0, 40], "color": "rgba(188, 61, 86, 0.2)"},
                        {"range": [40, 60], "color": "rgba(240, 217, 111, 0.2)"},
                        {"range": [60, 100], "color": "rgba(99, 169, 187, 0.2)"},
                    ],
                    "threshold": {
                        "line": {"color": "rgb(0, 72, 127)", "width": 3},
                        "thickness": 0.8,
                        "value": round(_wr, 1),
                    },
                },
            ))
            _fig_gauge.update_layout(height=250, margin=dict(t=60, b=20, l=40, r=40))
            st.plotly_chart(_fig_gauge, use_container_width=True)
            st.caption("Podíl uchazečů, kteří řadí Futurum na vyšší prioritu než tohoto konkurenta. "
                       "Nad 50 % = Futurum je preferované.")

            # Sekce shrnutí
            st.info(_shrnuti["pozice"])
            if _shrnuti["komunikace"]:
                st.info("**Komunikace a brand**\n\n" + _shrnuti["komunikace"])
            st.success("**Silné stránky Futura**\n\n" + _shrnuti["silne_stranky"])
            st.warning("**Příležitosti k růstu**\n\n" + _shrnuti["prilezitosti"])
            if _shrnuti["socialni_site"]:
                st.info("**Sociální sítě**\n\n" + _shrnuti["socialni_site"])

# ─── TAB 5: Spádovost (mapa) ──────────────────────────────────────────────

with tab_spadovost:
    st.header("Spádovost – odkud přicházejí uchazeči")

    # Uchazeči s naší školou
    _izo_cols_map = [f"skola_izo_{i}" for i in range(1, MAX_PRIORIT + 1) if f"skola_izo_{i}" in df.columns]
    _mask_map = df[_izo_cols_map].astype(str).apply(
        lambda row: row.str.strip().eq(NASE_SKOLA_IZO).any(), axis=1
    )
    _nasi_map = df[_mask_map]

    _typ_map = st.radio(
        "Zdroj škol:",
        ["Základní školy", "Střední školy"],
        horizontal=True,
        key="map_typ",
    )
    _col_map = "zakladni_skola" if _typ_map == "Základní školy" else "stredni_skola"

    if _col_map not in _nasi_map.columns:
        st.warning(f"Sloupec '{_col_map}' není v datech.")
    else:
        _skoly_series = _nasi_map[_col_map].dropna()
        _skoly_series = _skoly_series[_skoly_series.str.strip() != ""]

        if len(_skoly_series) == 0:
            st.info("Žádné záznamy.")
        else:
            # Extrahovat město z názvu školy
            _mesta_raw = _skoly_series.apply(extrahuj_mesto)
            _matched = _mesta_raw.dropna()
            _match_pct = len(_matched) / len(_skoly_series) * 100

            # Spočítat per město
            _city_counts = _matched.value_counts().reset_index()
            _city_counts.columns = ["mesto", "pocet"]
            # Rozdělit na města se souřadnicemi a bez
            _has_coords = _city_counts["mesto"].isin(CZECH_CITIES_COORDS)
            _no_coords = _city_counts[~_has_coords]
            _city_counts = _city_counts[_has_coords].copy()
            _city_counts["lat"] = _city_counts["mesto"].apply(lambda m: CZECH_CITIES_COORDS[m][0])
            _city_counts["lon"] = _city_counts["mesto"].apply(lambda m: CZECH_CITIES_COORDS[m][1])

            st.caption(f"Lokalizováno {len(_matched)}/{len(_skoly_series)} škol ({_match_pct:.0f} %)")

            if len(_city_counts) > 0:
                import math

                _fig_map = go.Figure()

                # Škálování velikosti bublin (sqrt pro lepší proporce)
                _max_pocet = _city_counts["pocet"].max()
                _city_counts["size_scaled"] = _city_counts["pocet"].apply(
                    lambda x: max(7, math.sqrt(x / _max_pocet) * 40)
                )
                # Popisky: jen číslo u malých, město+číslo u větších
                _city_counts["label"] = _city_counts.apply(
                    lambda r: str(r["pocet"]) if r["pocet"] < 3 else f"{r['mesto']}  {r['pocet']}",
                    axis=1,
                )

                _fig_map.add_trace(go.Scattermapbox(
                    lat=_city_counts["lat"],
                    lon=_city_counts["lon"],
                    mode="markers+text",
                    marker=dict(
                        size=_city_counts["size_scaled"],
                        color="rgba(55, 83, 109, 0.6)",
                    ),
                    text=_city_counts["label"],
                    textposition="top center",
                    textfont=dict(size=10, color="#333"),
                    hoverinfo="text",
                    hovertext=_city_counts.apply(
                        lambda r: f"<b>{r['mesto']}</b><br>Počet uchazečů: {r['pocet']}", axis=1
                    ),
                ))

                _fig_map.update_layout(
                    mapbox=dict(
                        style="carto-positron",
                        center=dict(
                            lat=_city_counts["lat"].mean(),
                            lon=_city_counts["lon"].mean(),
                        ),
                        zoom=10,
                    ),
                    height=650,
                    margin=dict(l=0, r=0, t=0, b=0),
                    showlegend=False,
                )
                st.plotly_chart(_fig_map, use_container_width=True)

                # Tabulka pod mapou
                st.subheader("Počet uchazečů podle lokality")
                _lokality_export = _city_counts[["mesto", "pocet"]].rename(
                    columns={"mesto": "Město / čtvrť", "pocet": "Počet uchazečů"}
                )
                st.dataframe(
                    _lokality_export,
                    use_container_width=True,
                    hide_index=True,
                )
                st.download_button(
                    "⬇️ Stáhnout celý seznam (CSV)",
                    data=_lokality_export.to_csv(index=False).encode("utf-8-sig"),
                    file_name=f"spadovost_lokality_{_col_map}.csv",
                    mime="text/csv",
                    key=f"dl_spad_lokality_{_col_map}",
                )

            # Obce bez souřadnic (fallback match, ale nemáme GPS)
            if len(_no_coords) > 0:
                with st.expander(f"Obce bez souřadnic na mapě ({_no_coords['pocet'].sum()} uchazečů)"):
                    _nocoord_export = _no_coords.rename(columns={"mesto": "Obec", "pocet": "Počet"})
                    st.dataframe(
                        _nocoord_export,
                        use_container_width=True,
                        hide_index=True,
                    )
                    st.download_button(
                        "⬇️ Stáhnout celý seznam (CSV)",
                        data=_nocoord_export.to_csv(index=False).encode("utf-8-sig"),
                        file_name=f"spadovost_obce_bez_souradnic_{_col_map}.csv",
                        mime="text/csv",
                        key=f"dl_spad_nocoord_{_col_map}",
                    )

            # Zcela nelokalizované školy
            _unmatched = _skoly_series[_mesta_raw.isna()]
            if len(_unmatched) > 0:
                _um_counts_all = _unmatched.value_counts().reset_index()
                _um_counts_all.columns = ["Škola", "Počet"]
                _um_counts = _um_counts_all.head(20)
                with st.expander(f"Nelokalizované školy ({len(_unmatched)})"):
                    st.caption(f"Zobrazeno top {len(_um_counts)} z {len(_um_counts_all)} unikátních škol")
                    st.dataframe(
                        _um_counts,
                        use_container_width=True,
                        hide_index=True,
                    )
                    st.download_button(
                        "⬇️ Stáhnout celý seznam (CSV)",
                        data=_um_counts_all.to_csv(index=False).encode("utf-8-sig"),
                        file_name=f"spadovost_nelokalizovane_{_col_map}.csv",
                        mime="text/csv",
                        key=f"dl_spad_unmatched_{_col_map}",
                    )

# ─── TAB 6: Přihlášky ───────────────────────────────────────────────────────

with tab_prihlasky:
    st.header("Prohlížeč přihlášek")

    # Filtry
    filter_cols = st.columns(3)

    with filter_cols[0]:
        # Filtr: na které prioritě je naše škola
        moznosti_priorit = ["Všichni"] + [f"Priorita {p}" for p in range(1, 4)]
        filtr_priorita = st.selectbox("Naše škola na prioritě:", moznosti_priorit)

    with filter_cols[1]:
        # Filtr: obor na naší škole
        vsechny_obory = set()
        for i in range(1, MAX_PRIORIT + 1):
            cn = f"obor_nazev_{i}"
            ci = f"skola_izo_{i}"
            if cn in df.columns and ci in df.columns:
                mask = df[ci].astype(str).str.strip() == NASE_SKOLA_IZO
                vals = df.loc[mask, cn].dropna().unique()
                vsechny_obory.update([v for v in vals if v])
        filtr_obor = st.multiselect("Obor (na naší škole):", sorted(vsechny_obory))

    with filter_cols[2]:
        # Filtr: stav
        if "stav" in df.columns:
            stavy = sorted(df["stav"].dropna().unique())
            filtr_stav = st.multiselect("Stav:", stavy)
        else:
            filtr_stav = []

    # Aplikovat filtry
    df_filtered = df.copy()

    if filtr_priorita != "Všichni":
        p_num = int(filtr_priorita.split()[-1])
        col_p = f"skola_izo_{p_num}"
        if col_p in df_filtered.columns:
            df_filtered = df_filtered[df_filtered[col_p].astype(str).str.strip() == NASE_SKOLA_IZO]

    if filtr_obor:
        mask = pd.Series(False, index=df_filtered.index)
        for i in range(1, MAX_PRIORIT + 1):
            cn = f"obor_nazev_{i}"
            ci = f"skola_izo_{i}"
            if cn in df_filtered.columns and ci in df_filtered.columns:
                is_nase = df_filtered[ci].astype(str).str.strip() == NASE_SKOLA_IZO
                is_obor = df_filtered[cn].isin(filtr_obor)
                mask = mask | (is_nase & is_obor)
        df_filtered = df_filtered[mask]

    if filtr_stav:
        df_filtered = df_filtered[df_filtered["stav"].isin(filtr_stav)]

    st.caption(f"Zobrazeno {len(df_filtered)} z {len(df)} přihlášek")

    # Anonymizovat a vybrat sloupce k zobrazení
    df_display = df_filtered.copy()

    # Nahradit jména anonymním ID
    if "uchazec_prijmeni" in df_display.columns and "uchazec_jmeno" in df_display.columns:
        df_display["uchazeč"] = [f"Uchazeč #{i+1:04d}" for i in range(len(df_display))]
        df_display = df_display.drop(columns=["uchazec_prijmeni", "uchazec_jmeno"], errors="ignore")
    elif "uchazec_prijmeni" in df_display.columns:
        df_display["uchazeč"] = [f"Uchazeč #{i+1:04d}" for i in range(len(df_display))]
        df_display = df_display.drop(columns=["uchazec_prijmeni"], errors="ignore")

    display_cols = []
    if "uchazeč" in df_display.columns:
        display_cols.append("uchazeč")
    for c in ["stav", "zamereni"]:
        if c in df_display.columns:
            display_cols.append(c)

    for i in range(1, MAX_PRIORIT + 1):
        for suffix in [f"skola_nazev_{i}", f"obor_nazev_{i}"]:
            if suffix in df_display.columns:
                display_cols.append(suffix)

    if display_cols:
        st.dataframe(
            df_display[display_cols],
            use_container_width=True,
            hide_index=True,
            height=600,
        )
    else:
        st.dataframe(df_display, use_container_width=True, hide_index=True, height=600)

# ─── TAB 7: Obory ───────────────────────────────────────────────────────────

with tab_obory:
    st.header("Přehled oborů")

    # Sbírat obory z přihlášek, které zahrnují naši školu
    st.subheader("Obory na naší škole")

    nase_obory = []
    for i in range(1, MAX_PRIORIT + 1):
        ci = f"skola_izo_{i}"
        co = f"obor_nazev_{i}"
        ck = f"kod_oboru_{i}"
        if ci in df.columns and co in df.columns:
            mask = df[ci].astype(str).str.strip() == NASE_SKOLA_IZO
            for _, row in df[mask].iterrows():
                nazev = str(row.get(co, "")).strip()
                kod = str(row.get(ck, "")).strip()
                if nazev and nazev != "nan":
                    nase_obory.append({"Kód oboru": kod, "Název oboru": nazev})

    if nase_obory:
        df_nase_obory = pd.DataFrame(nase_obory)
        obory_agg = (
            df_nase_obory.groupby(["Kód oboru", "Název oboru"])
            .size()
            .reset_index(name="Počet přihlášek")
            .sort_values("Počet přihlášek", ascending=False)
            .reset_index(drop=True)
        )
        obory_agg["Barva"] = obory_agg["Název oboru"].apply(_obor_color)

        col1, col2 = st.columns([1, 1])
        with col1:
            st.dataframe(
                obory_agg[["Kód oboru", "Název oboru", "Počet přihlášek"]],
                use_container_width=True,
                hide_index=True,
            )
        with col2:
            _fig_obory = go.Figure(
                go.Bar(
                    x=obory_agg["Název oboru"],
                    y=obory_agg["Počet přihlášek"],
                    marker_color=obory_agg["Barva"],
                    text=obory_agg["Počet přihlášek"],
                    textposition="outside",
                )
            )
            _fig_obory.update_layout(
                xaxis_title="",
                yaxis_title="Počet přihlášek",
                showlegend=False,
                margin=dict(t=20, b=80),
                xaxis_tickangle=-30,
                plot_bgcolor="white",
            )
            st.plotly_chart(_fig_obory, use_container_width=True)

    st.divider()
    st.subheader("Všechny obory napříč přihláškami")

    vsechny = []
    for i in range(1, MAX_PRIORIT + 1):
        co = f"obor_nazev_{i}"
        ck = f"kod_oboru_{i}"
        if co in df.columns:
            for _, row in df.iterrows():
                nazev = str(row.get(co, "")).strip()
                kod = str(row.get(ck, "")).strip()
                if nazev and nazev != "nan" and nazev != "":
                    vsechny.append({"Kód": kod, "Obor": nazev})

    if vsechny:
        df_vsechny = pd.DataFrame(vsechny)
        vsechny_agg = (
            df_vsechny.groupby(["Kód", "Obor"])
            .size()
            .reset_index(name="Počet")
            .sort_values("Počet", ascending=False)
            .reset_index(drop=True)
        )
        vsechny_agg["Barva"] = vsechny_agg["Obor"].apply(_obor_color)

        _fig_vsechny = go.Figure(
            go.Bar(
                x=vsechny_agg["Obor"].head(30),
                y=vsechny_agg["Počet"].head(30),
                marker_color=vsechny_agg["Barva"].head(30),
                text=vsechny_agg["Počet"].head(30),
                textposition="outside",
            )
        )
        _fig_vsechny.update_layout(
            xaxis_title="",
            yaxis_title="Počet přihlášek",
            showlegend=False,
            margin=dict(t=20, b=120),
            xaxis_tickangle=-40,
            plot_bgcolor="white",
            height=500,
        )
        st.plotly_chart(_fig_vsechny, use_container_width=True)

        with st.expander("Kompletní tabulka všech oborů"):
            st.dataframe(
                vsechny_agg[["Kód", "Obor", "Počet"]],
                use_container_width=True,
                hide_index=True,
                height=500,
            )
