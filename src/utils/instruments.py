"""Multi-instrument execution catalog (stock, 2x long ETFs, single-stock inverse ETFs).

Options chains are where institutional positioning and RV/IV dislocations appear
first, while agents may express the thesis via the Combo A option contract, 1x
underlying shares, or curated 2x long / single-stock inverse ETFs.
"""

from __future__ import annotations

from typing import Any

# Curated US single-stock 2x long ETFs ordered by liquidity (GraniteShares, Direxion, Defiance, T-Rex, Tradr)
LONG_2X_ETF_MAP: dict[str, tuple[str, ...]] = {
    "AAPL": ("AAPU",),
    "AMD": ("AMDL",),
    "AMZN": ("AMZU",),
    "ARM": ("ARMG",),
    "AVGO": ("AVL", "AVGU", "AVGX"),
    "BA": ("BOEU",),
    "BABA": ("BABX",),
    "BE": ("BEX",),
    "COIN": ("CONL",),
    "CRCL": ("CRCA",),
    "CRM": ("CRMG",),
    "CRWV": ("CRWU",),
    "DELL": ("DELX",),
    "GME": ("GMEU",),
    "GOOG": ("GGLL",),
    "GOOGL": ("GGLL",),
    "HOOD": ("ROBN", "HOOX"),
    "INTC": ("INTW",),
    "IONQ": ("IONX",),
    "IREN": ("IRE",),
    "META": ("METU",),
    "MSFT": ("MSFU",),
    "MSTR": ("MSTU", "MSTX"),
    "MU": ("MUU",),
    "NBIS": ("NBIU",),
    "NFLX": ("NFXL",),
    "NOW": ("NOWL",),
    "NVDA": ("NVDL",),
    "ORCL": ("ORCX",),
    "PLTR": ("PTIR", "PLTU"),
    "QCOM": ("QCMU",),
    "RKLB": ("RKLX",),
    "SMCI": ("SMCX",),
    "SOFI": ("SOFX",),
    "TSLA": ("TSLL",),
    "UBER": ("UBRL",),
    "VST": ("VSTL",),
}

# Curated US single-stock inverse (-1x / -2x) ETFs (single-stock only, no broad sector fallbacks)
INVERSE_ETF_MAP: dict[str, tuple[str, ...]] = {
    "AAPL": ("AAPD",),
    "AMD": ("AMDD", "AMDS"),
    "AMZN": ("AMZD",),
    "ARM": ("ARMD",),
    "AVGO": ("AVS", "AVGD"),
    "BABA": ("BABD",),
    "COIN": ("CONI",),
    "CRCL": ("CRCD",),
    "GOOG": ("GGLS",),
    "GOOGL": ("GGLS",),
    "HOOD": ("HOOZ", "RBND"),
    "INTC": ("INTD",),
    "META": ("METD",),
    "MSFT": ("MSFD",),
    "MSTR": ("MSTZ", "SMST"),
    "MU": ("MUD",),
    "NBIS": ("NBIZ",),
    "NFLX": ("NFXS",),
    "NVDA": ("NVD", "NVDD", "NVDQ"),
    "PLTR": ("PLTD", "PLTZ"),
    "SMCI": ("SMCZ",),
    "TSLA": ("TSLQ", "TSLZ", "TSDD"),
}


def build_execution_vehicles(ticker: str | None, recommended_contract: str | None = None) -> dict[str, Any]:
    """Return multi-instrument execution tickers for a pool candidate."""
    tk = str(ticker or "").strip().upper()
    return {
        "underlying_stock": tk or None,
        "option_contract": recommended_contract,
        "long_2x_etfs": list(LONG_2X_ETF_MAP.get(tk, ())),
        "inverse_etfs": list(INVERSE_ETF_MAP.get(tk, ())),
    }
