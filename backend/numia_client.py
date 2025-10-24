#!/usr/bin/env python3
"""
Numia API Client
Handles authentication and requests to Numia API for price and APR data
"""
import aiohttp
import logging
import os
import json
from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from config_loader import config

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent / '.env'
    load_dotenv(env_path)
except ImportError:
    pass  # python-dotenv not installed, will use system env vars

logger = logging.getLogger(__name__)


@dataclass
class TokenPrice:
    """Token price data from Numia"""
    symbol: str
    denom: str
    price: float
    last_updated: datetime


@dataclass
class StakingAPR:
    """Staking APR data"""
    symbol: str
    apr: float
    last_updated: datetime


class NumiaAPIClient:
    """Client for interacting with Numia API"""

    def __init__(self, api_key: Optional[str] = None, apr_config_path: Optional[str] = None):
        """
        Initialize Numia API client

        Args:
            api_key: Numia API key (starts with 'sk_')
                    If None, will try to read from environment
            apr_config_path: Path to APR configuration JSON file
        """
        self.api_key = api_key or os.getenv('NUMIA_API_KEY')
        if self.api_key:
            logger.info(f"Numia API client initialized with key: {self.api_key[:8]}...")
        else:
            logger.warning("No API key provided - will use fallback data")

        self.base_url = "https://api.numia.xyz"
        self.osmosis_url = "https://osmosis.numia.xyz"

        # Load token denoms and APR configs from master config
        self.token_denoms = config.get_token_denoms()
        self.apr_config = config.get_all_apr_configs()

    def _get_auth_headers(self) -> Dict[str, str]:
        """Get authentication headers for API requests"""
        if not self.api_key:
            return {}
        return {
            "Authorization": f"Bearer {self.api_key}"
        }

    async def get_osmosis_prices(self, symbols: List[str]) -> Dict[str, float]:
        """
        Get prices for tokens on Osmosis DEX

        Args:
            symbols: List of token symbols (e.g., ['OSMO', 'ATOM', 'TIA'])

        Returns:
            Dict mapping symbol to price in USD
        """
        logger.info(f"Fetching prices for {len(symbols)} tokens from Osmosis...")

        prices = {}

        # Build URL with multiple currency parameters using symbols
        params = [('currencies', symbol.upper()) for symbol in symbols]

        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self.osmosis_url}/prices"

                async with session.get(
                    url,
                    params=params,
                    headers=self._get_auth_headers(),
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as response:
                    if response.status == 200:
                        data = await response.json()

                        # Response format: [{"asset": "OSMO", "denom": "uosmo", "price_in_usdc": 0.117}]
                        if isinstance(data, list):
                            for item in data:
                                if 'asset' in item and 'price_in_usdc' in item:
                                    symbol = item['asset'].upper()
                                    price = float(item['price_in_usdc'])
                                    prices[symbol] = price
                                    logger.info(f"  ✅ {symbol}: ${price:.4f}")

                        logger.info(f"✅ Fetched {len(prices)} prices from Osmosis")
                    else:
                        error_text = await response.text()
                        logger.error(f"Osmosis API error {response.status}: {error_text}")

        except Exception as e:
            logger.error(f"Error fetching Osmosis prices: {e}")

        return prices

    async def get_staking_apr(self) -> Optional[float]:
        """
        Get Osmosis staking APR

        Returns:
            APR as percentage (e.g., 12.5 for 12.5%)
        """
        logger.info("Fetching Osmosis staking APR...")

        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self.osmosis_url}/apr"

                async with session.get(
                    url,
                    headers=self._get_auth_headers(),
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 200:
                        data = await response.json()

                        # Parse APR from response
                        # Format may vary - adjust as needed
                        if isinstance(data, dict):
                            if 'apr' in data:
                                apr = float(data['apr'])
                            elif 'staking_apr' in data:
                                apr = float(data['staking_apr'])
                            else:
                                # Try to find APR in nested data
                                apr = None
                                for value in data.values():
                                    if isinstance(value, (int, float)):
                                        apr = float(value)
                                        break
                        elif isinstance(data, (int, float)):
                            apr = float(data)
                        else:
                            apr = None

                        if apr is not None:
                            logger.info(f"✅ Osmosis staking APR: {apr}%")
                            return apr
                    else:
                        error_text = await response.text()
                        logger.error(f"APR API error {response.status}: {error_text}")

        except Exception as e:
            logger.error(f"Error fetching staking APR: {e}")

        return None

    async def get_token_prices(self, symbols: List[str]) -> Dict[str, TokenPrice]:
        """
        Get prices for multiple tokens

        Args:
            symbols: List of token symbols (e.g., ['ATOM', 'OSMO', 'TIA'])

        Returns:
            Dict mapping symbol to TokenPrice object
        """
        token_prices = {}

        # Fetch prices from Osmosis using symbols
        if symbols:
            prices = await self.get_osmosis_prices(symbols)

            for symbol, price in prices.items():
                denom = self.token_denoms.get(symbol)
                token_prices[symbol] = TokenPrice(
                    symbol=symbol,
                    denom=denom or 'unknown',
                    price=price,
                    last_updated=datetime.now(timezone.utc)
                )

        # Log tokens without prices
        for symbol in symbols:
            if symbol.upper() not in token_prices:
                logger.warning(f"  {symbol}: No price data available")

        return token_prices

    async def get_all_aprs(self, symbols: List[str], use_scraper: bool = True) -> Dict[str, Dict]:
        """
        Get APRs for all supported tokens
        Uses Keplr scraping with multi-tier caching fallback

        Args:
            symbols: List of token symbols
            use_scraper: If True, scrape APRs from Keplr (default True)

        Returns:
            Dict mapping symbol to APR data with format:
            {
                'ATOM': {'apr': 16.8, 'status': 'ok'/'fallback', 'source': 'keplr/cached/config'}
            }
        """
        aprs = {}

        if use_scraper:
            try:
                from apr_scraper import APRScraper

                logger.info(f"Fetching APRs for {len(symbols)} tokens...")

                async with APRScraper() as scraper:
                    # This NEVER fails - always returns values (fresh/stale/fallback)
                    scraped_aprs = await scraper.get_multiple_aprs(symbols)

                # Convert to expected format
                for symbol, apr_value in scraped_aprs.items():
                    symbol_upper = symbol.upper()

                    # Check if this token has skip_apr_scraping enabled
                    token_config = self.apr_config.get(symbol_upper, {})
                    skip_scraping = config.get_token_config(symbol_upper).get('skip_apr_scraping', False) if config.get_token_config(symbol_upper) else False

                    if apr_value == 0 and not skip_scraping:
                        # Scraping failed, no cache available, and NOT a skip_scraping token
                        aprs[symbol_upper] = {
                            'apr': 0.0,
                            'status': 'error',
                            'source': 'unavailable'
                        }
                    elif apr_value == 0 and skip_scraping:
                        # This token skips scraping, use config fallback
                        fallback_apr = token_config.get('fallback_apr', 10.0)
                        aprs[symbol_upper] = {
                            'apr': fallback_apr,
                            'status': 'ok',
                            'source': 'config'
                        }
                    else:
                        # Scraped or cached value
                        aprs[symbol_upper] = {
                            'apr': apr_value,
                            'status': 'ok',
                            'source': 'keplr'
                        }

            except Exception as e:
                logger.error(f"APR scraper failed: {e}, using config fallbacks")
                # Fall through to config-only mode

        # Fallback: If scraper disabled or failed catastrophically, return 0
        if not use_scraper or not aprs:
            logger.error("APR scraper disabled or failed, returning 0 for all tokens")
            for symbol in symbols:
                symbol_upper = symbol.upper()

                if symbol_upper in aprs:
                    continue

                aprs[symbol_upper] = {
                    'apr': 0.0,
                    'status': 'error',
                    'source': 'scraper_disabled'
                }

        return aprs


# Test function
async def test_client():
    """Test the Numia API client"""
    client = NumiaAPIClient()  # Will need API key in production

    symbols = ['ATOM', 'OSMO', 'TIA', 'JUNO', 'HUAHUA', 'DYM', 'SAGA', 'NLS']

    print("Testing Numia API Client\n" + "=" * 60)

    # Test price fetching
    print("\nFetching prices...")
    prices = await client.get_token_prices(symbols)

    # Test APR fetching
    print("\nFetching APRs...")
    aprs = await client.get_all_aprs(symbols)

    print("\n" + "=" * 60)
    print("Results:")
    for symbol in symbols:
        price_data = prices.get(symbol)
        apr = aprs.get(symbol)

        price_str = f"${price_data.price:.4f}" if price_data else "N/A"
        apr_str = f"{apr:.2f}%" if apr else "N/A"

        print(f"{symbol}: {price_str} @ {apr_str} APR")


if __name__ == "__main__":
    import asyncio
    asyncio.run(test_client())
