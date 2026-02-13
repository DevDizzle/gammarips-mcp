import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

# Import tools (assuming src is in path or run with python -m pytest)
from tools.overnight_signals import (
    get_overnight_signals,
    get_signal_detail,
    get_top_movers,
    get_market_themes
)

@pytest.mark.asyncio
async def test_get_overnight_signals_free_tier():
    with patch("tools.overnight_signals.fs_client") as mock_fs, \
         patch("tools.overnight_signals.bq_client") as mock_bq:
        
        # Setup mock return
        mock_signals = [
            {"ticker": "FSLY", "overnight_score": 9, "technicals": "secret"},
            {"ticker": "AAPL", "overnight_score": 6, "technicals": "secret"}
        ]
        mock_fs.get_overnight_signals = AsyncMock(return_value=mock_signals)
        
        # Call with FREE tier
        user_info = {"tier": "FREE"}
        result = await get_overnight_signals(limit=10, _user_info=user_info)
        
        # Verify restrictions
        # Should filter out score < 7 (AAPL has 6, but mock return list is filtered BY the tool logic? 
        # No, the tool calls fs_client with min_score=7 if FREE)
        
        # Check calling args
        mock_fs.get_overnight_signals.assert_called_with(
            date=datetime.now().strftime("%Y-%m-%d"),
            direction="ALL",
            min_score=7, # Enforced for FREE
            limit=10
        )
        
        # Verify paid fields removed from result
        signals = result["signals"]
        assert len(signals) == 2 # The mock returned 2, assuming FS returned what was asked. 
        # Actually FS client logic handles the filtering. 
        # But here we mocked the return.
        # The tool logic loops over returned signals and strips fields.
        
        assert "technicals" not in signals[0]
        assert "upgrade" in result

@pytest.mark.asyncio
async def test_get_overnight_signals_edge_tier():
    with patch("tools.overnight_signals.fs_client") as mock_fs:
        mock_signals = [{"ticker": "FSLY", "overnight_score": 9, "technicals": "available"}]
        mock_fs.get_overnight_signals = AsyncMock(return_value=mock_signals)
        
        user_info = {"tier": "EDGE"}
        result = await get_overnight_signals(min_score=5, _user_info=user_info)
        
        # Check calling args - min_score should be 5 as requested
        mock_fs.get_overnight_signals.assert_called_with(
            date=datetime.now().strftime("%Y-%m-%d"),
            direction="ALL",
            min_score=5,
            limit=20
        )
        
        # Verify paid fields kept
        assert "technicals" in result["signals"][0]
        assert "upgrade" not in result

@pytest.mark.asyncio
async def test_get_signal_detail_free_tier():
    user_info = {"tier": "FREE"}
    result = await get_signal_detail("FSLY", _user_info=user_info)
    assert "error" in result
    assert "upgrade_required" == result["error"]

@pytest.mark.asyncio
async def test_get_signal_detail_paid_tier():
    with patch("tools.overnight_signals.fs_client") as mock_fs:
        mock_fs.get_signal_detail = AsyncMock(return_value={"ticker": "FSLY", "data": "full"})
        
        user_info = {"tier": "EDGE"}
        result = await get_signal_detail("FSLY", _user_info=user_info)
        
        assert result["ticker"] == "FSLY"
        assert result["data"] == "full"

@pytest.mark.asyncio
async def test_get_top_movers():
    with patch("tools.overnight_signals.bq_client") as mock_bq:
        mock_bq.get_top_movers = AsyncMock(return_value={"top_bullish": []})
        
        await get_top_movers(count=5)
        mock_bq.get_top_movers.assert_called_with(count=5)

@pytest.mark.asyncio
async def test_get_market_themes_free_tier():
    with patch("tools.overnight_signals.fs_client") as mock_fs:
        mock_themes = [{"name": "AI", "tickers": ["NVDA", "AMD"]}]
        mock_fs.get_market_themes = AsyncMock(return_value=mock_themes)
        
        user_info = {"tier": "FREE"}
        result = await get_market_themes(_user_info=user_info)
        
        # Tickers should be removed
        assert "tickers" not in result["themes"][0]
        assert result["themes"][0]["name"] == "AI"
