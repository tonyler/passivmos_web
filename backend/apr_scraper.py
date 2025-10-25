#!/usr/bin/env python3
"""
APR Scraper for Passive Income Calculator
Scrapes APR data from Keplr wallet with multi-tier caching
"""

import asyncio
import aiohttp
import re
import json
import time
from typing import Dict, Optional, List
from pathlib import Path
import logging
from playwright.async_api import async_playwright, Page, Browser
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from config_loader import config

logger = logging.getLogger(__name__)

# Global lock to ensure only ONE scraping operation at a time across all instances
_global_scraping_lock = asyncio.Lock()

class APRScraper:
    """APR scraper for Cosmos ecosystem tokens - Keplr only with robust caching"""

    def __init__(self, cache_dir: str = "data/cache"):
        self.session = None
        self.browser = None
        self.context = None
        self.playwright = None

        # Multi-tier caching
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.cache_dir / "apr_cache.json"

        self.memory_cache = {}  # In-memory cache
        self.cache_timestamps = {}
        self.fresh_duration = 600  # 10 minutes = fresh (matches background update interval)
        self.stale_duration = 3600  # 1 hour = stale but usable

        # Load config fallbacks
        self.config_fallbacks = {}
        for symbol in config.get_enabled_tokens():
            token_config = config.get_token_config(symbol)
            if token_config:
                self.config_fallbacks[symbol] = token_config.get('fallback_apr', 10.0)

        # Browser config
        self.browser_timeout = 30000  # 30 seconds
        self.max_retries = 3
        self._browser_lock = asyncio.Lock()

        # Load cached data on init
        self._load_cache_from_disk()

    def _load_cache_from_disk(self):
        """Load cache from disk on startup"""
        if not self.cache_file.exists():
            return

        try:
            with open(self.cache_file, 'r') as f:
                data = json.load(f)
                self.memory_cache = data.get('cache', {})
                self.cache_timestamps = data.get('timestamps', {})
            logger.info(f"Loaded {len(self.memory_cache)} cached APRs from disk")
        except Exception as e:
            logger.error(f"Error loading cache from disk: {e}")

    def _save_cache_to_disk(self):
        """Save cache to disk"""
        try:
            data = {
                'cache': self.memory_cache,
                'timestamps': self.cache_timestamps,
                'last_updated': time.time()
            }
            with open(self.cache_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving cache to disk: {e}")

    def _is_cache_fresh(self, token: str) -> bool:
        """Check if cached APR is fresh (< 1 hour)"""
        if token not in self.memory_cache or token not in self.cache_timestamps:
            return False
        age = time.time() - self.cache_timestamps[token]
        return age < self.fresh_duration

    def _is_cache_stale(self, token: str) -> bool:
        """Check if cached APR is stale but usable (< 24 hours)"""
        if token not in self.memory_cache or token not in self.cache_timestamps:
            return False
        age = time.time() - self.cache_timestamps[token]
        return age < self.stale_duration

    def _get_cache_age(self, token: str) -> Optional[float]:
        """Get age of cached value in hours"""
        if token not in self.cache_timestamps:
            return None
        age_seconds = time.time() - self.cache_timestamps[token]
        return age_seconds / 3600

    def _set_cache(self, token: str, apr: float):
        """Cache APR value in memory and disk"""
        self.memory_cache[token] = apr
        self.cache_timestamps[token] = time.time()
        self._save_cache_to_disk()
        logger.info(f"{token}: Cached {apr}% APR")

    def _get_cached_or_fallback(self, token: str) -> float:
        """
        Get APR with fallback
        Priority: fresh cache > stale cache > config fallback (if skip_apr_scraping) > 0
        """
        # Try fresh cache
        if self._is_cache_fresh(token):
            age = self._get_cache_age(token)
            logger.info(f"{token}: Using fresh cache ({age:.1f}h old)")
            return self.memory_cache[token]

        # Try stale cache
        if self._is_cache_stale(token):
            age = self._get_cache_age(token)
            logger.warning(f"{token}: Using stale cache ({age:.1f}h old)")
            return self.memory_cache[token]

        # No cache available - check if this is a skip_apr_scraping token
        token_config = config.get_token_config(token.upper())
        if token_config and token_config.get('skip_apr_scraping', False):
            fallback_apr = token_config.get('fallback_apr', 0.0)
            logger.info(f"{token}: Using config fallback APR: {fallback_apr}%")
            # Cache this value so it's available next time
            self.memory_cache[token] = fallback_apr
            self.cache_timestamps[token] = time.time()
            self._save_cache_to_disk()
            return fallback_apr

        # Failed - return 0
        logger.error(f"{token}: No cache available, returning 0")
        return 0.0

    async def __aenter__(self):
        """Async context manager entry"""
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit with proper cleanup"""
        await self.cleanup_browser()
        if self.session:
            await self.session.close()

    async def cleanup_browser(self):
        """Clean up browser resources safely"""
        try:
            if self.context:
                await self.context.close()
                self.context = None
            if self.browser:
                await self.browser.close()
                self.browser = None
            if self.playwright:
                await self.playwright.stop()
                self.playwright = None
        except Exception as e:
            logger.error(f"Error during browser cleanup: {e}")

    async def init_browser(self):
        """Initialize browser for web scraping with proper error handling"""
        async with self._browser_lock:
            if not self.browser:
                try:
                    self.playwright = await async_playwright().start()
                    self.browser = await self.playwright.chromium.launch(
                        headless=True,
                        args=[
                            '--no-sandbox',
                            '--disable-dev-shm-usage',
                            '--disable-gpu',
                            '--disable-web-security',
                            '--disable-features=VizDisplayCompositor'
                        ]
                    )
                    self.context = await self.browser.new_context(
                        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                        viewport={'width': 1280, 'height': 720},
                        ignore_https_errors=True
                    )

                    # Set default timeouts
                    self.context.set_default_timeout(self.browser_timeout)
                    self.context.set_default_navigation_timeout(self.browser_timeout)

                    logger.info("Browser initialized successfully")
                except Exception as e:
                    logger.error(f"Failed to initialize browser: {e}")
                    await self.cleanup_browser()
                    raise

    async def scrape_keplr_apr(self, token_symbol: str) -> Optional[float]:
        """Scrape APR from Keplr wallet - returns None if fails"""
        for attempt in range(self.max_retries):
            page = None
            try:
                await self.init_browser()

                keplr_urls = config.get_keplr_urls()
                url = keplr_urls.get(token_symbol)

                if not url:
                    logger.warning(f"{token_symbol}: No Keplr URL configured")
                    return None

                page = await self.context.new_page()
                page.set_default_timeout(self.browser_timeout)
                page.set_default_navigation_timeout(self.browser_timeout)

                try:
                    await page.goto(url, wait_until='networkidle', timeout=self.browser_timeout)
                    await page.wait_for_timeout(3000)
                except Exception as nav_error:
                    logger.warning(f"{token_symbol}: Navigation failed (attempt {attempt + 1}): {nav_error}")
                    if attempt < self.max_retries - 1:
                        continue
                    return None

                # Primary XPath selector
                apr_selector = "//*[@id='__next']/div[2]/div[2]/div/div[1]/div/div[2]/div/div/div/div[1]/div[2]/p"
                apr_locator = page.locator(f"xpath={apr_selector}")

                if await apr_locator.count() > 0:
                    apr_text = await apr_locator.first.inner_text()
                    if apr_text:
                        apr_match = re.search(r'(\d+\.?\d*)%', apr_text)
                        if apr_match:
                            apr_value = float(apr_match.group(1))
                            self._set_cache(token_symbol, apr_value)
                            logger.info(f"{token_symbol}: Scraped {apr_value}% from Keplr")
                            return apr_value

                # Try alternative selectors
                for selector in ["text=% APR", "[data-testid*='apr']", ".apr-value", ".staking-apr"]:
                    try:
                        elements = await page.locator(selector).all()
                        for element in elements:
                            text = await element.inner_text()
                            if text and '%' in text:
                                apr_match = re.search(r'(\d+\.?\d*)%', text)
                                if apr_match:
                                    apr_value = float(apr_match.group(1))
                                    if 0 < apr_value < 100:
                                        self._set_cache(token_symbol, apr_value)
                                        logger.info(f"{token_symbol}: Scraped {apr_value}% from Keplr (alt selector)")
                                        return apr_value
                    except Exception:
                        continue

                logger.warning(f"{token_symbol}: Could not find APR (attempt {attempt + 1})")

                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                return None

            except Exception as e:
                logger.error(f"{token_symbol}: Scraping error (attempt {attempt + 1}): {e}")
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                return None
            finally:
                if page:
                    try:
                        await page.close()
                    except Exception:
                        pass

        logger.error(f"{token_symbol}: Failed to scrape after {self.max_retries} attempts")
        return None

    async def get_multiple_aprs(self, tokens: List[str]) -> Dict[str, float]:
        """
        Get APRs for multiple tokens
        Returns cached/fallback values if scraping fails.
        Uses global lock to ensure only one scraping operation at a time.
        """
        logger.info(f"Fetching APRs for {len(tokens)} tokens...")

        apr_dict = {}

        # First, check which tokens need scraping (not fresh in cache)
        tokens_to_scrape = []
        for token in tokens:
            token = token.upper()
            if self._is_cache_fresh(token):
                # Use fresh cache
                apr_dict[token] = self._get_cached_or_fallback(token)
            else:
                # Needs scraping
                tokens_to_scrape.append(token)

        # If nothing to scrape, return cached/fallback values
        if not tokens_to_scrape:
            logger.info("All tokens have fresh cache")
            return apr_dict

        # Use global lock to ensure only ONE scraping operation at a time
        # If another scrape is in progress, wait for it to finish then use cache
        if _global_scraping_lock.locked():
            logger.info("Another scraping operation in progress, waiting for it to finish...")
            async with _global_scraping_lock:
                # Scraping finished, check cache again
                for token in tokens_to_scrape:
                    apr_dict[token] = self._get_cached_or_fallback(token)
                return apr_dict

        # Acquire lock and scrape tokens - ONE AT A TIME (sequential)
        async with _global_scraping_lock:
            logger.info(f"Scraping {len(tokens_to_scrape)} tokens sequentially: {', '.join(tokens_to_scrape)}")

            results = []
            for token in tokens_to_scrape:
                try:
                    # Skip if configured to skip scraping
                    token_config = config.get_token_config(token)
                    if token_config and token_config.get('skip_apr_scraping', False):
                        logger.info(f"{token}: Skipping scraping (configured)")
                        results.append((token, None))
                        continue

                    # Scrape with timeout per token (30s max)
                    try:
                        apr = await asyncio.wait_for(
                            self.scrape_keplr_apr(token),
                            timeout=30.0
                        )
                        results.append((token, apr))
                        logger.info(f"{token}: Scraped successfully - {apr}%")

                        # Small delay between scrapes to avoid overwhelming the system
                        await asyncio.sleep(0.5)

                    except asyncio.TimeoutError:
                        logger.error(f"{token}: Scraping timed out after 30s")
                        results.append((token, None))

                except Exception as e:
                    logger.error(f"{token}: Exception during scraping: {e}")
                    results.append((token, None))

            # Process results
            for result in results:
                if isinstance(result, Exception):
                    logger.error(f"Exception in scraping: {result}")
                    continue

                token, apr = result
                if apr is not None:
                    apr_dict[token] = apr
                else:
                    # Scraping failed, use cache or fallback
                    apr_dict[token] = self._get_cached_or_fallback(token)

            # Clean up browser
            await self.cleanup_browser()

        # Ensure ALL tokens have a value (should already, but double-check)
        for token in tokens:
            token = token.upper()
            if token not in apr_dict:
                apr_dict[token] = self._get_cached_or_fallback(token)

        logger.info(f"✅ Returned APRs for {len(apr_dict)}/{len(tokens)} tokens")
        return apr_dict

# Example usage and testing
async def test_apr_scraper():
    """Test the APR scraper"""
    async with APRScraper() as scraper:
        # Test individual token
        atom_apr = await scraper.get_token_apr('ATOM')
        print(f"ATOM APR: {atom_apr}%")

        # Test multiple tokens
        tokens = ['ATOM', 'OSMO', 'TIA', 'JUNO']
        aprs = await scraper.get_multiple_aprs(tokens)

        print("\nAll APRs:")
        for token, apr in aprs.items():
            print(f"{token}: {apr}%")

if __name__ == "__main__":
    asyncio.run(test_apr_scraper())