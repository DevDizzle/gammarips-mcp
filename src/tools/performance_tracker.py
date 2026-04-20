"""
Performance tracking tools for GammaRips MCP
"""

import logging
import os
from typing import Any, Dict, List, Optional

import httpx
from google.cloud import bigquery

logger = logging.getLogger(__name__)

# Initialize client
try:
    client = bigquery.Client(project="profitscout-fida8")
except Exception as e:
    logger.error(f"Failed to initialize BigQuery client: {e}")
    client = None

POLYGON_API_KEY = os.getenv("POLYGON_API_KEY", "").strip() or None


def _polygon_option_mid(contract: str) -> Optional[float]:
    """Return the current mid price for a Polygon option contract (e.g.
    "O:FIX260515C01780000"). Returns None on any failure or when POLYGON_API_KEY
    is not mounted — callers must handle None gracefully."""
    if not POLYGON_API_KEY or not contract:
        return None
    try:
        # Underlying is embedded in the OCC-style contract; Polygon's
        # snapshot endpoint takes underlying + option symbol.
        # e.g. O:FIX260515C01780000 -> underlying "FIX"
        if contract.startswith("O:"):
            tail = contract[2:]
            # ticker chars until the first digit
            underlying = ""
            for ch in tail:
                if ch.isdigit():
                    break
                underlying += ch
        else:
            underlying = contract.split(":")[0]

        url = f"https://api.polygon.io/v3/snapshot/options/{underlying}/{contract}"
        resp = httpx.get(url, params={"apiKey": POLYGON_API_KEY}, timeout=5.0)
        resp.raise_for_status()
        data = resp.json().get("results") or {}
        lq = (data.get("last_quote") or {})
        bid, ask = lq.get("bid"), lq.get("ask")
        if bid is not None and ask is not None and ask > 0:
            return round((bid + ask) / 2, 4)
        # Fallback to last trade if quote not available
        lt = (data.get("last_trade") or {})
        price = lt.get("price")
        return float(price) if price is not None else None
    except Exception as e:
        logger.warning(f"Polygon option snapshot failed for {contract}: {e}")
        return None

def get_signal_performance(
    scan_date: Optional[str] = None,
    ticker: Optional[str] = None,
    direction: Optional[str] = None,
    outcome: Optional[str] = None,
    limit: int = 50
) -> List[Dict[str, Any]]:
    """
    Track how signals actually performed against market outcomes.
    
    Args:
        scan_date: Filter by date (YYYY-MM-DD).
        ticker: Filter to specific ticker.
        direction: "bull" or "bear".
        outcome: "win" or "loss" to filter.
        limit: Max results (default 50).
        
    Returns:
        Performance records with: ticker, direction, score, entry_price, current_price, pnl_pct, outcome, scan_date.
    """
    if not client:
        return [{"error": "BigQuery client not initialized"}]

    try:
        # scan_date is STRING in this table
        base_query = """
            SELECT 
                ticker, direction, signal_score as score, signal_price as entry_price, current_price, 
                pct_change as pnl_pct, is_win, scan_date 
            FROM `profitscout-fida8.profit_scout.signal_performance`
            WHERE 1=1
        """
        
        query_params = []
        
        if scan_date:
            base_query += " AND scan_date = @scan_date"
            query_params.append(bigquery.ScalarQueryParameter("scan_date", "STRING", scan_date))
            
        if ticker:
            base_query += " AND ticker = @ticker"
            query_params.append(bigquery.ScalarQueryParameter("ticker", "STRING", ticker))
            
        if direction:
            base_query += " AND LOWER(direction) = LOWER(@direction)"
            query_params.append(bigquery.ScalarQueryParameter("direction", "STRING", direction))
            
        if outcome:
            # outcome 'win' -> is_win = TRUE, 'loss' -> is_win = FALSE
            is_win_val = (outcome.lower() == "win")
            base_query += " AND is_win = @is_win"
            query_params.append(bigquery.ScalarQueryParameter("is_win", "BOOL", is_win_val))
            
        base_query += " ORDER BY scan_date DESC, score DESC LIMIT @limit"
        query_params.append(bigquery.ScalarQueryParameter("limit", "INTEGER", limit))
        
        job_config = bigquery.QueryJobConfig(query_parameters=query_params)
        query_job = client.query(base_query, job_config=job_config)
        
        results = []
        for row in query_job.result():
            r = dict(row)
            # Add 'outcome' string field for compatibility
            r['outcome'] = 'WIN' if r.get('is_win') else 'LOSS'
            results.append(r)
            
        return results
        
    except Exception as e:
        logger.error(f"Error in get_signal_performance: {e}")
        return [{"error": str(e)}]

def get_win_rate_summary(
    days: int = 30
) -> Dict[str, Any]:
    """
    Aggregate performance statistics.
    
    Args:
        days: Lookback period in days (default 30).
        
    Returns:
        Summary statistics object.
    """
    if not client:
        return {"error": "BigQuery client not initialized"}

    try:
        # Calculate start date based on days lookback
        # scan_date is STRING, so we use PARSE_DATE
        # Direction comparisons use UPPER() so the aggregation is casing-tolerant
        # against any schema drift in the signal_performance table.
        query = """
            WITH stats AS (
                SELECT
                    COUNT(*) as total_signals,
                    COUNTIF(is_win = TRUE) as wins,
                    AVG(pct_change) as avg_return,
                    COUNTIF(UPPER(direction) = 'BULLISH' AND is_win = TRUE) as bull_wins,
                    COUNTIF(UPPER(direction) = 'BULLISH') as bull_total,
                    COUNTIF(UPPER(direction) = 'BEARISH' AND is_win = TRUE) as bear_wins,
                    COUNTIF(UPPER(direction) = 'BEARISH') as bear_total,
                    MAX(pct_change) as max_return,
                    MIN(pct_change) as min_return
                FROM `profitscout-fida8.profit_scout.signal_performance`
                WHERE PARSE_DATE('%Y-%m-%d', scan_date) >= DATE_SUB(CURRENT_DATE(), INTERVAL @days DAY)
            ),
            best_ticker AS (
                SELECT ticker, AVG(pct_change) as avg_pnl
                FROM `profitscout-fida8.profit_scout.signal_performance`
                WHERE PARSE_DATE('%Y-%m-%d', scan_date) >= DATE_SUB(CURRENT_DATE(), INTERVAL @days DAY)
                GROUP BY ticker
                ORDER BY avg_pnl DESC
                LIMIT 1
            ),
            worst_ticker AS (
                SELECT ticker, AVG(pct_change) as avg_pnl
                FROM `profitscout-fida8.profit_scout.signal_performance`
                WHERE PARSE_DATE('%Y-%m-%d', scan_date) >= DATE_SUB(CURRENT_DATE(), INTERVAL @days DAY)
                GROUP BY ticker
                ORDER BY avg_pnl ASC
                LIMIT 1
            )
            SELECT 
                s.*,
                b.ticker as best_performer,
                w.ticker as worst_performer
            FROM stats s
            LEFT JOIN best_ticker b ON 1=1
            LEFT JOIN worst_ticker w ON 1=1
        """
        
        query_params = [
            bigquery.ScalarQueryParameter("days", "INTEGER", days)
        ]
        
        job_config = bigquery.QueryJobConfig(query_parameters=query_params)
        query_job = client.query(query, job_config=job_config)
        
        result = {}
        for row in query_job.result():
            result = dict(row)
            break
            
        if not result:
            return {"message": "No performance data found for this period"}
            
        # Calculate percentages
        total = result.get('total_signals', 0)
        if total > 0:
            result['win_rate'] = round((result.get('wins', 0) / total) * 100, 2)
        else:
            result['win_rate'] = 0.0
            
        bull_total = result.get('bull_total', 0)
        if bull_total > 0:
            result['bull_win_rate'] = round((result.get('bull_wins', 0) / bull_total) * 100, 2)
            
        bear_total = result.get('bear_total', 0)
        if bear_total > 0:
            result['bear_win_rate'] = round((result.get('bear_wins', 0) / bear_total) * 100, 2)

        return result
        
    except Exception as e:
        logger.error(f"Error in get_win_rate_summary: {e}")
        return {"error": str(e)}


def get_open_position() -> List[Dict[str, Any]]:
    """
    Returns currently-open V5.3 paper positions from forward_paper_ledger
    with live Polygon option prices and unrealized P&L. An "open" position is
    a ledger row where exit_timestamp IS NULL and scan_date is within the last
    ~5 trading days (longer than the 3-day hold window to be safe).

    Returns:
        List of {ticker, direction, recommended_contract, entry_price,
                 target_price, stop_price, current_mid, unrealized_return_pct,
                 days_since_entry, scan_date, entry_timestamp}. Empty list
        if there are no open positions. If POLYGON_API_KEY is unavailable,
        current_mid and unrealized_return_pct will be null.
    """
    if not client:
        return [{"error": "BigQuery client not initialized"}]

    try:
        # An "open position" is a ledger row with an ACTUAL entry fill
        # (entry_price IS NOT NULL) that has not yet closed. Stale stubs
        # where entry never happened are excluded — they're not live trades.
        query = """
            SELECT
                ticker, direction, recommended_contract,
                entry_price, target_price, stop_price,
                entry_timestamp, scan_date,
                policy_version
            FROM `profitscout-fida8.profit_scout.forward_paper_ledger`
            WHERE exit_timestamp IS NULL
              AND entry_price IS NOT NULL
              AND IFNULL(is_skipped, FALSE) = FALSE
              AND scan_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
            ORDER BY scan_date DESC, ticker
        """
        results = []
        for row in client.query(query).result():
            r = dict(row)
            # Normalize date/timestamp for JSON.
            for k, v in list(r.items()):
                if hasattr(v, "isoformat"):
                    r[k] = v.isoformat()

            # Enrich with live option price + unrealized P&L.
            contract = r.get("recommended_contract")
            entry = r.get("entry_price")
            mid = _polygon_option_mid(contract) if contract else None
            r["current_mid"] = mid
            if mid is not None and entry not in (None, 0):
                try:
                    r["unrealized_return_pct"] = round(((mid / float(entry)) - 1) * 100, 2)
                except Exception:
                    r["unrealized_return_pct"] = None
            else:
                r["unrealized_return_pct"] = None

            # Days since entry (simple calendar-day proxy).
            from datetime import datetime, timezone as _tz
            et = r.get("entry_timestamp")
            if et:
                try:
                    dt = datetime.fromisoformat(str(et).replace("Z", "+00:00"))
                    r["days_since_entry"] = (datetime.now(_tz.utc) - dt).days
                except Exception:
                    r["days_since_entry"] = None
            else:
                r["days_since_entry"] = None

            results.append(r)
        return results

    except Exception as e:
        logger.error(f"Error in get_open_position: {e}")
        return [{"error": str(e)}]


def get_position_history(
    days: int = 30,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """
    Returns realized (closed) V5.3 paper trades from the last N days, row-level,
    for chat-agent answers like "show me recent wins/losses" or "how did FIX do".
    PIT-safe: only rows where exit_timestamp IS NOT NULL AND DATE(exit_timestamp)
    < today (no intraday-open rows).

    Args:
        days: Lookback window in trading-day-equivalents (default 30).
        limit: Max rows (default 50, clamped 1-200).

    Returns:
        List of {scan_date, ticker, direction, recommended_contract, entry_price,
                 exit_price, realized_return_pct, exit_reason, entry_timestamp,
                 exit_timestamp, policy_version}.
    """
    if not client:
        return [{"error": "BigQuery client not initialized"}]

    limit = max(1, min(int(limit), 200))

    try:
        query = """
            SELECT
                scan_date, ticker, direction, recommended_contract,
                entry_price, exit_price, realized_return_pct,
                exit_reason, entry_timestamp, exit_timestamp, policy_version
            FROM `profitscout-fida8.profit_scout.forward_paper_ledger`
            WHERE exit_timestamp IS NOT NULL
              AND DATE(exit_timestamp) < CURRENT_DATE()
              AND scan_date >= DATE_SUB(CURRENT_DATE(), INTERVAL @days DAY)
              AND IFNULL(is_skipped, FALSE) = FALSE
            ORDER BY exit_timestamp DESC
            LIMIT @limit
        """
        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("days", "INTEGER", days),
            bigquery.ScalarQueryParameter("limit", "INTEGER", limit),
        ])

        results = []
        for row in client.query(query, job_config=job_config).result():
            r = dict(row)
            for k, v in list(r.items()):
                if hasattr(v, "isoformat"):
                    r[k] = v.isoformat()
            results.append(r)
        return results

    except Exception as e:
        logger.error(f"Error in get_position_history: {e}")
        return [{"error": str(e)}]
