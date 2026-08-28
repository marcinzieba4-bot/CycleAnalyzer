"""Country universe: 10 DM + 14 EM economies, data-source codes, targets.

Sources (all free, no API key):
  BIS SDMX  - policy rates (WS_CBPOL), CPI y/y (WS_LONG_CPI), broad real
              effective exchange rates (WS_EER)
  OECD via DBnomics - composite leading indicator (amplitude adjusted);
              business confidence as fallback where the CLI is not compiled
  FRED      - 10y government bond yields (OECD MEI long rates, IRLTLT01*)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Country:
    iso2: str
    iso3: str
    name: str
    bloc: str            # "DM" | "EM"
    ccy: str
    infl_target: float   # central bank target (midpoint), % y/y
    cli_code: str | None    # OECD CLI series code (DBnomics), None = no CLI
    fred_10y: str | None    # FRED series id for 10y yield, None = unavailable
    cb: str              # central bank short name


def _cli(iso3: str) -> str:
    return f"{iso3}.M.LI.IX._Z.AA.IX._Z.H"


def _bcicp(iso3: str) -> str:
    return f"{iso3}.M.BCICP.IX._Z.AA.IX._Z.H"


COUNTRIES: dict[str, Country] = {c.iso2: c for c in [
    # ---- Developed markets -------------------------------------------------
    Country("US", "USA", "United States", "DM", "USD", 2.0, _cli("USA"), "IRLTLT01USM156N", "Fed"),
    Country("XM", "EA20", "Euro area",    "DM", "EUR", 2.0, _bcicp("EA20"), "IRLTLT01EZM156N", "ECB"),
    Country("JP", "JPN", "Japan",         "DM", "JPY", 2.0, _cli("JPN"), "IRLTLT01JPM156N", "BoJ"),
    Country("GB", "GBR", "United Kingdom","DM", "GBP", 2.0, _cli("GBR"), "IRLTLT01GBM156N", "BoE"),
    Country("CA", "CAN", "Canada",        "DM", "CAD", 2.0, _cli("CAN"), "IRLTLT01CAM156N", "BoC"),
    Country("AU", "AUS", "Australia",     "DM", "AUD", 2.5, _cli("AUS"), "IRLTLT01AUM156N", "RBA"),
    Country("CH", "CHE", "Switzerland",   "DM", "CHF", 1.0, _bcicp("CHE"), "IRLTLT01CHM156N", "SNB"),
    Country("SE", "SWE", "Sweden",        "DM", "SEK", 2.0, _bcicp("SWE"), "IRLTLT01SEM156N", "Riksbank"),
    Country("NO", "NOR", "Norway",        "DM", "NOK", 2.0, _bcicp("NOR"), "IRLTLT01NOM156N", "Norges Bank"),
    Country("NZ", "NZL", "New Zealand",   "DM", "NZD", 2.0, _bcicp("NZL"), "IRLTLT01NZM156N", "RBNZ"),
    # ---- Emerging markets --------------------------------------------------
    Country("CN", "CHN", "China",         "EM", "CNY", 3.0, _cli("CHN"), None, "PBoC"),
    Country("IN", "IND", "India",         "EM", "INR", 4.0, _cli("IND"), None, "RBI"),
    Country("BR", "BRA", "Brazil",        "EM", "BRL", 3.0, _cli("BRA"), None, "BCB"),
    Country("MX", "MEX", "Mexico",        "EM", "MXN", 3.0, _cli("MEX"), "IRLTLT01MXM156N", "Banxico"),
    Country("ZA", "ZAF", "South Africa",  "EM", "ZAR", 4.5, _cli("ZAF"), "IRLTLT01ZAM156N", "SARB"),
    Country("TR", "TUR", "Turkiye",       "EM", "TRY", 5.0, _cli("TUR"), None, "TCMB"),
    Country("PL", "POL", "Poland",        "EM", "PLN", 2.5, _bcicp("POL"), "IRLTLT01PLM156N", "NBP"),
    Country("HU", "HUN", "Hungary",       "EM", "HUF", 3.0, _bcicp("HUN"), "IRLTLT01HUM156N", "MNB"),
    Country("CZ", "CZE", "Czechia",       "EM", "CZK", 2.0, _bcicp("CZE"), "IRLTLT01CZM156N", "CNB"),
    Country("ID", "IDN", "Indonesia",     "EM", "IDR", 2.5, _cli("IDN"), None, "BI"),
    Country("KR", "KOR", "Korea",         "EM", "KRW", 2.0, _cli("KOR"), "IRLTLT01KRM156N", "BoK"),
    Country("CL", "CHL", "Chile",         "EM", "CLP", 3.0, _bcicp("CHL"), "IRLTLT01CLM156N", "BCCh"),
    Country("CO", "COL", "Colombia",      "EM", "COP", 3.0, _bcicp("COL"), None, "BanRep"),
    Country("TH", "THA", "Thailand",      "EM", "THB", 2.0, None, None, "BoT"),
]}

DM = [c for c in COUNTRIES.values() if c.bloc == "DM"]
EM = [c for c in COUNTRIES.values() if c.bloc == "EM"]
