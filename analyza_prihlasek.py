#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Analýza přihlášek na střední školy – přijímací řízení 1. kolo
==============================================================

SPUŠTĚNÍ:
    python3 analyza_prihlasek.py

POTŘEBNÉ SOUBORY:
    - Vstupní CSV soubor (viz VSTUPNI_CSV níže)

POTŘEBNÉ KNIHOVNY:
    pip install pandas openpyxl requests

KONFIGURACE:
    - Upravte konstanty v sekci "KONFIGURACE" níže (IZO školy, cesty k souborům)
    - Číselník škol se automaticky stáhne z MŠMT rejstříku (JSON-LD)
    - Číselník oborů je zabudovaný ve skriptu (MŠMT/CERMAT)
    - Pro offline režim: při prvním spuštění se číselník škol uloží do cache souboru

VÝSTUPY:
    - Excel soubor s obohacenou tabulkou (s přeloženými názvy škol a oborů)
    - Excel soubor s analytickými přehledy (listy pro prioritu 1, 2, 3)
"""

from __future__ import annotations

import os
import sys
import json
import pandas as pd
import requests
from collections import Counter
from pathlib import Path

# =============================================================================
# KONFIGURACE – upravte dle potřeby
# =============================================================================

NASE_SKOLA_IZO = "16996593"
NASE_SKOLA_NAZEV = "Střední škola Futurum"

# Cesty k souborům (relativní k umístění skriptu)
SCRIPT_DIR = Path(__file__).parent

# Vstupní CSV – automaticky najde soubor končící na .csv v adresáři skriptu
VSTUPNI_CSV = None  # Nastavte explicitně, nebo se najde automaticky

# Výstupní soubory
VYSTUP_OBOHACENA_TABULKA = SCRIPT_DIR / "prihlášky_obohacené.xlsx"
VYSTUP_ANALYZA = SCRIPT_DIR / "analyza_konkurence.xlsx"

# Cache pro číselník škol (aby se nestahoval pokaždé znovu)
CACHE_SKOLY = SCRIPT_DIR / "cache_ciselnik_skol.json"

# URL pro stažení rejstříku škol z MŠMT (JSON-LD)
MSMT_REJSTRIK_URL = (
    "https://lkod-ftp.msmt.gov.cz/00022985/"
    "e9c07729-877e-4af0-be4a-9d36e45806ae/"
    "rssz-cela-cr-2025-09-30.jsonld"
)

# Maximální počet priorit v přihlášce
MAX_PRIORIT = 5

# =============================================================================
# ČÍSELNÍK OBORŮ VZDĚLÁNÍ (MŠMT / CERMAT – nařízení vlády č. 211/2010 Sb.)
# =============================================================================

CISELNIK_OBORU = {
    # Gymnázia
    "79-41-K/41": "Gymnázium",
    "79-41-K/61": "Gymnázium (šestileté)",
    "79-41-K/81": "Gymnázium (osmileté)",
    "79-42-K/41": "Gymnázium se sportovní přípravou",
    "79-42-K/61": "Gymnázium se sportovní přípravou (šestileté)",
    "79-42-K/81": "Gymnázium se sportovní přípravou (osmileté)",
    "79-43-K/61": "Dvojjazyčné gymnázium",
    # Lycea
    "78-42-M/01": "Technické lyceum",
    "78-42-M/02": "Ekonomické lyceum",
    "78-42-M/03": "Pedagogické lyceum",
    "78-42-M/04": "Zdravotnické lyceum",
    "78-42-M/05": "Přírodovědné lyceum",
    "78-42-M/06": "Kombinované lyceum",
    "78-42-M/07": "Vojenské lyceum",
    "78-42-M/08": "Lyceum",
    # Ekonomika
    "63-41-M/01": "Ekonomika a podnikání",
    "63-41-M/02": "Obchodní akademie",
    # Hotelnictví a cestovní ruch
    "65-42-M/01": "Hotelnictví",
    "65-42-M/02": "Cestovní ruch",
    # Pedagogika a sociální činnost
    "75-31-M/01": "Předškolní a mimoškolní pedagogika",
    "75-31-M/02": "Pedagogika pro asistenty ve školství",
    "75-41-M/01": "Sociální činnost",
    # Právo a veřejná správa
    "68-42-M/01": "Bezpečnostně právní činnost",
    "68-43-M/01": "Veřejnosprávní činnost",
    # Informatika
    "18-20-M/01": "Informační technologie",
    # Strojírenství a doprava
    "23-41-M/01": "Strojírenství",
    "23-45-M/01": "Dopravní prostředky",
    # Elektrotechnika
    "26-41-M/01": "Elektrotechnika",
    "26-45-M/01": "Telekomunikace",
    # Stavebnictví
    "36-43-M/01": "Stavební materiály",
    "36-45-M/01": "Technická zařízení budov",
    "36-47-M/01": "Stavebnictví",
    "36-46-M/01": "Geodézie a katastr nemovitostí",
    # Chemie
    "28-44-M/01": "Aplikovaná chemie",
    # Potravinářství
    "29-41-M/01": "Technologie potravin",
    "29-42-M/01": "Analýza potravin",
    "29-54-H/01": "Cukrář",
    # Textil a oděvnictví
    "31-41-M/01": "Textilnictví",
    "31-43-M/01": "Oděvnictví",
    # Dřevo a nábytek
    "33-42-M/01": "Nábytkářská a dřevařská výroba",
    "33-43-M/01": "Výroba hudebních nástrojů",
    # Polygrafie
    "34-41-M/01": "Polygrafie",
    "34-42-M/01": "Obalová technika",
    "34-53-L/01": "Reprodukční grafik",
    # Kůže a plasty
    "32-41-M/01": "Zpracování usní, plastů a pryže",
    # Doprava a logistika
    "37-41-M/01": "Provoz a ekonomika dopravy",
    "37-42-M/01": "Logistické a finanční služby",
    # Požární ochrana
    "39-08-M/01": "Požární ochrana",
    # Ekologie
    "16-01-M/01": "Ekologie a životní prostředí",
    "16-02-M/01": "Průmyslová ekologie",
    # Zemědělství
    "41-41-M/01": "Agropodnikání",
    "41-44-M/01": "Zahradnictví",
    "41-46-M/01": "Lesnictví",
    "43-41-M/01": "Veterinářství",
    # Zdravotnictví
    "53-41-M/01": "Zdravotnický asistent",
    "53-41-M/02": "Nutriční asistent",
    "53-41-M/03": "Praktická sestra",
    "53-43-M/01": "Laboratorní asistent",
    "53-44-M/01": "Dentální hygiena",
    "53-44-M/03": "Asistent zubního technika",
    # Optika
    "69-41-L/01": "Kosmetické služby",
    "69-42-M/01": "Oční optik",
    "69-51-H/01": "Kadeřník",
    # Knihkupectví a informační služby
    "66-41-L/01": "Obchodník",
    "66-43-M/01": "Knihkupecké a nakladatelské činnosti",
    "72-41-M/01": "Informační služby",
    # Umění
    "82-41-M/01": "Užitá malba",
    "82-41-M/02": "Užitá fotografie a média",
    "82-41-M/03": "Scénická a výstavní tvorba",
    "82-41-M/04": "Průmyslový design",
    "82-41-M/05": "Grafický design",
    "82-41-M/06": "Výtvarné zpracování kovů a drahých kamenů",
    "82-41-M/07": "Modelářství a návrhářství oděvů",
    "82-41-M/08": "Výtvarné zpracování keramiky a porcelánu",
    "82-41-M/09": "Uměleckořemeslná stavba hudebních nástrojů",
    "82-41-M/10": "Průmysl. zpracování skla a světelná tvorba",
    "82-41-M/11": "Design interiéru",
    "82-41-M/12": "Výtvarné zpracování skla a světelná tvorba",
    "82-41-M/13": "Výtvarné zpracování kovů a drahých kamenů",
    "82-41-M/14": "Textilní výtvarnictví",
    "82-41-M/15": "Grafika",
    "82-41-M/17": "Multimediální tvorba",
    "82-42-M/01": "Konzervátorství a restaurátorství",
    "82-44-M/01": "Hudba",
    "82-44-P/01": "Hudba",
    "82-45-M/01": "Zpěv",
    "82-45-P/01": "Zpěv",
    "82-46-M/01": "Tanec",
    "82-46-M/02": "Tanec (konzervatoř)",
    "82-46-P/01": "Tanec",
    "82-46-P/02": "Tanec",
    "82-47-M/01": "Hudebně dramatické umění",
    "82-47-P/01": "Hudebně dramatické umění",
    "82-51-L/02": "Uměleckořemeslné zpracování dřeva",
    "82-51-L/06": "Uměleckořemeslné zpracování kovů",
    # Učební obory (H)
    "82-51-H/03": "Uměleckořemeslné zpracování kamene",
    "65-51-H/01": "Kuchař – číšník",
    "33-56-H/01": "Truhlář",
    "66-51-H/01": "Prodavač",
    "66-52-H/01": "Aranžér",
    # Nástavbové studium (L/51, L/52)
    "75-41-L/51": "Sociální činnost (nástavbové)",
    "64-41-L/51": "Podnikání (nástavbové)",
    "65-41-L/51": "Gastronomie (nástavbové)",
    "69-41-L/52": "Vlasová kosmetika (nástavbové)",
    # Další obory L
    "65-41-L/01": "Gastronomie",
    "68-42-L/01": "Bezpečnostně právní činnost",
    "41-43-L/01": "Chovatel koní",
    # Zdravotnictví – další
    "53-41-M/04": "Zubní technik",
}


# =============================================================================
# FUNKCE PRO NAČTENÍ ČÍSELNÍKU ŠKOL
# =============================================================================

def nacti_ciselnik_skol_z_msmt(cache_path: Path, url: str) -> dict[str, str]:
    """
    Stáhne rejstřík škol z MŠMT (JSON-LD) a vytvoří mapování identifikátor -> název školy.
    Pokrývá IZO, RED_IZO i IČO (s i bez úvodních nul) pro maximální pokrytí.
    Výsledek se uloží do cache souboru, aby se příště nestahoval znovu.
    """
    # Zkusit načíst z cache
    if cache_path.exists():
        print(f"  Načítám číselník škol z cache: {cache_path.name}")
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)

    print(f"  Stahuji rejstřík škol z MŠMT ({url})...")
    try:
        response = requests.get(url, timeout=120)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as e:
        print(f"  VAROVÁNÍ: Nelze stáhnout rejstřík škol: {e}")
        print("  Skript bude pokračovat bez překladu IZO na názvy.")
        return {}

    # Sestavit mapování – IZO, RED_IZO, IČO (s i bez úvodních nul)
    izo_map = {}
    for entry in data.get("list", []):
        nazev_po = entry.get("uplnyNazev", "")
        red_izo = entry.get("redIzo", "")
        ico = entry.get("ico", "")

        # RED_IZO – identifikátor právnické osoby
        if red_izo:
            izo_map[red_izo] = nazev_po
            izo_map[red_izo.lstrip("0") or "0"] = nazev_po

        # IČO – identifikační číslo organizace
        if ico:
            izo_map[ico] = nazev_po
            izo_map[ico.lstrip("0") or "0"] = nazev_po

        # IZO – identifikátor činnosti školy/zařízení
        for skola_zarizeni in entry.get("skolyAZarizeni", []):
            izo = skola_zarizeni.get("izo", "")
            if izo:
                izo_map[izo] = nazev_po
                izo_map[izo.lstrip("0") or "0"] = nazev_po

    # Ruční doplnění škol, které v rejstříku chybí (nové školy apod.)
    RUCNI_DOPLNENI = {
        "250013517": "Klinická univerzitní škola EduVia, gymnázium a SŠ pedagogická",
    }
    izo_map.update(RUCNI_DOPLNENI)

    # Uložit do cache
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(izo_map, f, ensure_ascii=False, indent=0)
    print(f"  Uloženo {len(izo_map)} záznamů do cache: {cache_path.name}")

    return izo_map


def nacti_ciselnik_skol_z_csv(df: pd.DataFrame) -> dict[str, str]:
    """
    Vytvoří mapování IZO -> název školy z dat v samotném CSV souboru
    (sloupce stredni_skola a stredni_skola_izo).
    Slouží jako záložní zdroj pro IZO kódy, které nejsou v rejstříku MŠMT.
    """
    izo_map = {}
    if "stredni_skola" in df.columns and "stredni_skola_izo" in df.columns:
        for _, row in df[["stredni_skola_izo", "stredni_skola"]].dropna().iterrows():
            izo = str(row["stredni_skola_izo"]).strip()
            nazev = str(row["stredni_skola"]).strip()
            if izo and nazev:
                izo_map[izo] = nazev
    return izo_map


# =============================================================================
# FUNKCE PRO PŘEKLAD KÓDŮ
# =============================================================================

def preloz_izo(izo: str, ciselnik_msmt: dict, ciselnik_csv: dict) -> str:
    """Přeloží IZO kód na název školy. Vrátí název nebo kód s příponou (nenalezeno)."""
    if not izo or pd.isna(izo):
        return ""
    izo = str(izo).strip()
    if not izo:
        return ""
    # Zkusit MŠMT rejstřík
    if izo in ciselnik_msmt:
        return ciselnik_msmt[izo]
    # Zkusit záložní číselník z CSV
    if izo in ciselnik_csv:
        return ciselnik_csv[izo]
    return f"{izo} (nenalezeno)"


def preloz_obor(kod: str) -> str:
    """Přeloží kód oboru na název. Vrátí název nebo kód s příponou (nenalezeno)."""
    if not kod or pd.isna(kod):
        return ""
    kod = str(kod).strip()
    if not kod:
        return ""
    if kod in CISELNIK_OBORU:
        return CISELNIK_OBORU[kod]
    return f"{kod} (nenalezeno)"


# =============================================================================
# FUNKCE PRO NAČTENÍ DAT
# =============================================================================

def najdi_vstupni_csv(script_dir: Path) -> Path:
    """Najde vstupní CSV soubor v adresáři skriptu."""
    csv_soubory = list(script_dir.glob("*.csv"))
    if not csv_soubory:
        print("CHYBA: Nenalezen žádný CSV soubor v adresáři skriptu.")
        sys.exit(1)
    # Preferovat soubor s "přijímací" nebo "prihlasek" v názvu
    for csv in csv_soubory:
        if "jímací" in csv.name.lower() or "prihlás" in csv.name.lower() or "prihlašen" in csv.name.lower():
            return csv
    return csv_soubory[0]


def nacti_data(cesta_csv: Path) -> pd.DataFrame:
    """Načte CSV soubor s přihláškami. Zkouší různé kódování a oddělovače."""
    print(f"Načítám data z: {cesta_csv.name}")

    # Zkusit různá kódování
    for encoding in ["utf-8-sig", "utf-8", "cp1250", "latin-1"]:
        for sep in [";", ","]:
            try:
                df = pd.read_csv(cesta_csv, sep=sep, encoding=encoding, dtype=str)
                # Ověřit, že máme klíčové sloupce
                if "skola_izo_1" in df.columns and "kod_oboru_1" in df.columns:
                    print(f"  Úspěšně načteno: {len(df)} řádků, kódování={encoding}, oddělovač='{sep}'")
                    return df
            except Exception:
                continue

    print("CHYBA: Nepodařilo se načíst CSV soubor. Zkontrolujte formát.")
    sys.exit(1)


# =============================================================================
# FUNKCE PRO OBOHACENÍ TABULKY
# =============================================================================

def obohat_tabulku(df: pd.DataFrame, ciselnik_skol_msmt: dict, ciselnik_skol_csv: dict) -> pd.DataFrame:
    """
    Doplní do DataFrame sloupce s názvy škol a oborů pro všechny priority.
    Nové sloupce: skola_nazev_1..5, obor_nazev_1..5
    """
    print("Obohacuji tabulku o názvy škol a oborů...")
    df_out = df.copy()

    for i in range(1, MAX_PRIORIT + 1):
        col_izo = f"skola_izo_{i}"
        col_obor = f"kod_oboru_{i}"
        col_nazev_skoly = f"skola_nazev_{i}"
        col_nazev_oboru = f"obor_nazev_{i}"

        if col_izo in df_out.columns:
            df_out[col_nazev_skoly] = df_out[col_izo].apply(
                lambda x: preloz_izo(x, ciselnik_skol_msmt, ciselnik_skol_csv)
            )
        else:
            df_out[col_nazev_skoly] = ""

        if col_obor in df_out.columns:
            df_out[col_nazev_oboru] = df_out[col_obor].apply(preloz_obor)
        else:
            df_out[col_nazev_oboru] = ""

    # Seřadit sloupce – vložit názvy hned za příslušné kódy
    novy_poradi = []
    for col in df.columns:
        novy_poradi.append(col)
        for i in range(1, MAX_PRIORIT + 1):
            if col == f"skola_izo_{i}":
                novy_poradi.append(f"skola_nazev_{i}")
            elif col == f"kod_oboru_{i}":
                novy_poradi.append(f"obor_nazev_{i}")

    # Přidat případné zbylé sloupce
    for col in df_out.columns:
        if col not in novy_poradi:
            novy_poradi.append(col)

    df_out = df_out[novy_poradi]

    # Statistika překladu
    nenalezeno_skoly = 0
    nenalezeno_obory = 0
    for i in range(1, MAX_PRIORIT + 1):
        col_ns = f"skola_nazev_{i}"
        col_no = f"obor_nazev_{i}"
        if col_ns in df_out.columns:
            nenalezeno_skoly += df_out[col_ns].str.contains("nenalezeno", na=False).sum()
        if col_no in df_out.columns:
            nenalezeno_obory += df_out[col_no].str.contains("nenalezeno", na=False).sum()

    print(f"  Nepřeložené školy: {nenalezeno_skoly}, Nepřeložené obory: {nenalezeno_obory}")
    return df_out


# =============================================================================
# FUNKCE PRO ANALÝZU KONKURENCE
# =============================================================================

def analyzuj_prioritu(
    df: pd.DataFrame,
    priorita: int,
    ciselnik_skol_msmt: dict,
    ciselnik_skol_csv: dict,
) -> pd.DataFrame | None:
    """
    Pro uchazeče, kteří mají naši školu na dané prioritě,
    zjistí, na které jiné školy a obory se hlásili.

    Vrátí DataFrame s přehledem konkurenčních škol/oborů.
    """
    col_izo = f"skola_izo_{priorita}"
    if col_izo not in df.columns:
        return None

    # Filtrovat uchazeče s naší školou na dané prioritě
    maska = df[col_izo].astype(str).str.strip() == NASE_SKOLA_IZO
    uchazeci = df[maska]
    pocet = len(uchazeci)

    if pocet == 0:
        print(f"  Priorita {priorita}: žádní uchazeči s naší školou")
        return None

    print(f"  Priorita {priorita}: {pocet} uchazečů má naši školu")

    # Sbírat konkurenční školy/obory z ostatních priorit
    konkurence = []
    for i in range(1, MAX_PRIORIT + 1):
        if i == priorita:
            continue
        col_i_izo = f"skola_izo_{i}"
        col_i_obor = f"kod_oboru_{i}"
        if col_i_izo not in uchazeci.columns:
            continue

        for _, row in uchazeci.iterrows():
            izo_val = str(row.get(col_i_izo, "")).strip()
            obor_val = str(row.get(col_i_obor, "")).strip()
            if izo_val and izo_val != "nan" and izo_val != NASE_SKOLA_IZO:
                nazev_skoly = preloz_izo(izo_val, ciselnik_skol_msmt, ciselnik_skol_csv)
                nazev_oboru = preloz_obor(obor_val) if obor_val and obor_val != "nan" else ""
                konkurence.append({
                    "priorita_konkurenta": i,
                    "izo_skoly": izo_val,
                    "nazev_skoly": nazev_skoly,
                    "kod_oboru": obor_val if obor_val != "nan" else "",
                    "nazev_oboru": nazev_oboru,
                })

    if not konkurence:
        print(f"    Žádné konkurenční přihlášky nalezeny")
        return None

    df_konk = pd.DataFrame(konkurence)

    # Agregace – top školy
    skoly_agg = (
        df_konk.groupby(["izo_skoly", "nazev_skoly"])
        .size()
        .reset_index(name="pocet_uchazecú")
        .sort_values("pocet_uchazecú", ascending=False)
    )

    # Agregace – top školy+obory
    skoly_obory_agg = (
        df_konk.groupby(["izo_skoly", "nazev_skoly", "kod_oboru", "nazev_oboru"])
        .size()
        .reset_index(name="pocet_uchazecú")
        .sort_values("pocet_uchazecú", ascending=False)
    )

    # Sloučit do jednoho výstupu – nejdřív souhrn škol, pak detail škol+oborů
    # Přidáme oddělovací řádek
    separator = pd.DataFrame([{
        "izo_skoly": "",
        "nazev_skoly": "--- DETAIL: ŠKOLY + OBORY ---",
        "kod_oboru": "",
        "nazev_oboru": "",
        "pocet_uchazecú": "",
    }])

    # Doplnit prázdné sloupce do skoly_agg
    skoly_agg["kod_oboru"] = ""
    skoly_agg["nazev_oboru"] = ""
    skoly_agg = skoly_agg[["izo_skoly", "nazev_skoly", "kod_oboru", "nazev_oboru", "pocet_uchazecú"]]

    # Hlavička
    hlavicka = pd.DataFrame([{
        "izo_skoly": "",
        "nazev_skoly": f"NAŠE ŠKOLA NA PRIORITĚ {priorita} – {pocet} uchazečů",
        "kod_oboru": "",
        "nazev_oboru": "",
        "pocet_uchazecú": "",
    }])

    separator2 = pd.DataFrame([{
        "izo_skoly": "",
        "nazev_skoly": "--- SOUHRN: KONKURENČNÍ ŠKOLY ---",
        "kod_oboru": "",
        "nazev_oboru": "",
        "pocet_uchazecú": "",
    }])

    vysledek = pd.concat([hlavicka, separator2, skoly_agg, separator, skoly_obory_agg], ignore_index=True)
    return vysledek


# =============================================================================
# ULOŽENÍ VÝSTUPŮ
# =============================================================================

def uloz_obohacenou_tabulku(df: pd.DataFrame, cesta: Path):
    """Uloží obohacenou tabulku do Excelu."""
    print(f"Ukládám obohacenou tabulku: {cesta.name}")
    with pd.ExcelWriter(cesta, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Přihlášky", index=False)

        # Formátování – automatická šířka sloupců
        ws = writer.sheets["Přihlášky"]
        for col_idx, col in enumerate(df.columns, 1):
            max_len = max(
                len(str(col)),
                df[col].astype(str).str.len().max() if len(df) > 0 else 0,
            )
            ws.column_dimensions[ws.cell(row=1, column=col_idx).column_letter].width = min(max_len + 2, 60)

    print(f"  Uloženo: {len(df)} řádků")


def uloz_analyzu(analyzy: dict[int, pd.DataFrame | None], cesta: Path):
    """Uloží analytické přehledy do Excelu jako samostatné listy."""
    print(f"Ukládám analýzu konkurence: {cesta.name}")
    with pd.ExcelWriter(cesta, engine="openpyxl") as writer:
        for priorita, df_analyza in analyzy.items():
            sheet_name = f"Priorita {priorita}"
            if df_analyza is not None and len(df_analyza) > 0:
                df_analyza.to_excel(writer, sheet_name=sheet_name, index=False)

                # Formátování
                ws = writer.sheets[sheet_name]
                for col_idx, col in enumerate(df_analyza.columns, 1):
                    max_len = max(
                        len(str(col)),
                        df_analyza[col].astype(str).str.len().max() if len(df_analyza) > 0 else 0,
                    )
                    ws.column_dimensions[ws.cell(row=1, column=col_idx).column_letter].width = min(max_len + 2, 60)
            else:
                pd.DataFrame({"info": [f"Žádní uchazeči s {NASE_SKOLA_NAZEV} na prioritě {priorita}"]}).to_excel(
                    writer, sheet_name=sheet_name, index=False
                )
    print("  Uloženo.")


# =============================================================================
# HLAVNÍ FUNKCE
# =============================================================================

def main():
    print("=" * 70)
    print(f"  Analýza přihlášek – {NASE_SKOLA_NAZEV} (IZO: {NASE_SKOLA_IZO})")
    print("=" * 70)
    print()

    # 1. Najít a načíst vstupní CSV
    global VSTUPNI_CSV
    if VSTUPNI_CSV is None:
        VSTUPNI_CSV = najdi_vstupni_csv(SCRIPT_DIR)
    else:
        VSTUPNI_CSV = Path(VSTUPNI_CSV)

    df = nacti_data(VSTUPNI_CSV)
    print()

    # 2. Načíst číselníky
    print("Načítám číselníky...")
    ciselnik_skol_msmt = nacti_ciselnik_skol_z_msmt(CACHE_SKOLY, MSMT_REJSTRIK_URL)
    ciselnik_skol_csv = nacti_ciselnik_skol_z_csv(df)
    print(f"  Číselník škol MŠMT: {len(ciselnik_skol_msmt)} záznamů")
    print(f"  Číselník škol z CSV: {len(ciselnik_skol_csv)} záznamů")
    print(f"  Číselník oborů: {len(CISELNIK_OBORU)} záznamů")
    print()

    # 3. Obohacení tabulky
    df_obohacena = obohat_tabulku(df, ciselnik_skol_msmt, ciselnik_skol_csv)
    print()

    # 4. Analýza priorit
    print("Analýza konkurence...")
    analyzy = {}
    for priorita in range(1, 4):  # Priority 1, 2, 3
        analyzy[priorita] = analyzuj_prioritu(df, priorita, ciselnik_skol_msmt, ciselnik_skol_csv)
    print()

    # 5. Uložení výstupů
    uloz_obohacenou_tabulku(df_obohacena, VYSTUP_OBOHACENA_TABULKA)
    uloz_analyzu(analyzy, VYSTUP_ANALYZA)
    print()

    # 6. Stručný souhrn na konzoli
    print("=" * 70)
    print("  SOUHRN")
    print("=" * 70)
    print(f"  Celkem uchazečů: {len(df)}")
    for priorita in range(1, 4):
        col_izo = f"skola_izo_{priorita}"
        if col_izo in df.columns:
            pocet = (df[col_izo].astype(str).str.strip() == NASE_SKOLA_IZO).sum()
            print(f"  Naše škola na prioritě {priorita}: {pocet} uchazečů")
    print()
    print(f"  Výstup 1: {VYSTUP_OBOHACENA_TABULKA.name}")
    print(f"  Výstup 2: {VYSTUP_ANALYZA.name}")
    print("=" * 70)


if __name__ == "__main__":
    main()
