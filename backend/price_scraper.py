#!/usr/bin/env python3
"""
Price and APR data fetcher for webapp using Numia API
Replaces web scraping with direct API calls to Numia
"""
import asyncio
import logging
import os
from typing import Dict, Optional
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from config_loader import config

# Import Numia API client
from numia_client import NumiaAPIClient

logger = logging.getLogger(__name__)

@dataclass
class TokenData:
    """Token price and APR data"""
    symbol: str
    price: float
    apr: float
    apr_status: str  # 'ok', 'error', 'fallback'
    apr_source: str  # 'scraped', 'config', 'scraping_failed', etc.
    last_updated: datetime

class PriceAPRScraper:
    """Fetches prices and APR from Numia API"""

    def __init__(self, cache_dir: str = "data/cache", api_key: str = None):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.cache_dir / "token_data.json"

        # Initialize Numia API client
        self.api_key = api_key or os.getenv('NUMIA_API_KEY')
        self.numia_client = NumiaAPIClient(api_key=self.api_key)

        # Supported tokens - dynamically loaded from config
        self.tokens = config.get_enabled_tokens()

    async def scrape_all(self) -> Dict[str, TokenData]:
        """Fetch all token data from Numia API and cache it"""
        logger.info("Fetching token data from Numia API...")

        try:
            # Fetch prices from Numia
            price_data = await self.numia_client.get_token_prices(self.tokens)

            # Fetch APRs from Numia
            apr_data = await self.numia_client.get_all_aprs(self.tokens)

            # Combine data
            token_data = {}
            for symbol in self.tokens:
                price_obj = price_data.get(symbol)
                price = price_obj.price if price_obj else 0.0

                apr_info = apr_data.get(symbol, {'apr': 10.0, 'status': 'error', 'source': 'default'})

                token_data[symbol] = TokenData(
                    symbol=symbol,
                    price=price,
                    apr=apr_info['apr'],
                    apr_status=apr_info['status'],
                    apr_source=apr_info['source'],
                    last_updated=datetime.now(timezone.utc)
                )

            # Cache the data
            self._save_cache(token_data)

            logger.info(f"Fetched data for {len(token_data)} tokens")
            return token_data

        except Exception as e:
            logger.error(f"Error fetching token data: {e}")
            # Try to load from cache on error
            cached = self.load_cache()
            if cached:
                logger.info("Returning cached data due to fetch error")
                return cached
            raise


    def _save_cache(self, token_data: Dict[str, TokenData]):
        """Save token data to cache file"""
        cache_data = {
            symbol: {
                'symbol': data.symbol,
                'price': data.price,
                'apr': data.apr,
                'apr_status': data.apr_status,
                'apr_source': data.apr_source,
                'last_updated': data.last_updated.isoformat()
            }
            for symbol, data in token_data.items()
        }

        with open(self.cache_file, 'w') as f:
            json.dump(cache_data, f, indent=2)

        logger.info(f"💾 Cached data saved to {self.cache_file}")

    def load_cache(self) -> Optional[Dict[str, TokenData]]:
        """Load token data from cache"""
        if not self.cache_file.exists():
            return None

        try:
            with open(self.cache_file, 'r') as f:
                cache_data = json.load(f)

            token_data = {}
            for symbol, data in cache_data.items():
                token_data[symbol] = TokenData(
                    symbol=data['symbol'],
                    price=data['price'],
                    apr=data['apr'],
                    apr_status=data.get('apr_status', 'ok'),  # Backwards compatible
                    apr_source=data.get('apr_source', 'config'),  # Backwards compatible
                    last_updated=datetime.fromisoformat(data['last_updated'])
                )

            logger.info(f"📂 Loaded cached data for {len(token_data)} tokens")
            return token_data

        except Exception as e:
            logger.error(f"Error loading cache: {e}")
            return None

    def get_token_data(self, symbol: str) -> Optional[TokenData]:
        """Get cached token data for a specific symbol"""
        cache = self.load_cache()
        if cache:
            return cache.get(symbol.upper())
        return None

# Background scraper task
async def background_scraper(interval: int = 300):
    """Run scraper in background every N seconds"""
    scraper = PriceAPRScraper()

    while True:
        try:
            await scraper.scrape_all()
            logger.info(f"⏰ Next scrape in {interval} seconds...")
            await asyncio.sleep(interval)
        except Exception as e:
            logger.error(f"Background scraper error: {e}")
            await asyncio.sleep(60)  # Wait 1 minute on error

if __name__ == "__main__":
    # Test scraper
    logging.basicConfig(level=logging.INFO)

    async def test():
        scraper = PriceAPRScraper()
        data = await scraper.scrape_all()
        print("\n📊 Scraped Data:")
        for symbol, token_data in data.items():
            print(f"{symbol}: ${token_data.price:.4f} @ {token_data.apr:.2f}% APR")

    asyncio.run(test())
