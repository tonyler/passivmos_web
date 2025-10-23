#!/usr/bin/env python3
"""
APR Scraper for Passive Income Calculator
Scrapes APR data from various sources including Keplr wallet
"""

import asyncio
import aiohttp
import re
from typing import Dict, Optional, List, Tuple
from datetime import datetime, timezone
import logging
from playwright.async_api import async_playwright, Page, Browser
import time
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from config_loader import config

logger = logging.getLogger(__name__)

class APRScraper:
    """Advanced APR scraper for Cosmos ecosystem tokens"""

    def __init__(self):
        self.session = None
        self.browser = None
        self.context = None
        self.playwright = None
        self.cache = {}
        self.cache_expiry = {}
        self.cache_duration = 3600  # 1 hour
        self.browser_timeout = 30000  # 30 seconds
        self.max_retries = 3
        self._browser_lock = asyncio.Lock()  # Prevent concurrent browser access

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

    def _is_cache_valid(self, token: str) -> bool:
        """Check if cached APR is still valid"""
        if token not in self.cache or token not in self.cache_expiry:
            return False
        return time.time() < self.cache_expiry[token]

    def _set_cache(self, token: str, apr: float):
        """Cache APR value"""
        self.cache[token] = apr
        self.cache_expiry[token] = time.time() + self.cache_duration

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

    async def scrape_keplr_apr(self, token_symbol: str, chain_name: str) -> Optional[float]:
        """Scrape APR from Keplr wallet interface with retry logic"""
        for attempt in range(self.max_retries):
            page = None
            try:
                await self.init_browser()

                # Keplr URLs loaded from config
                keplr_urls = config.get_keplr_urls()

                url = keplr_urls.get(token_symbol)
                if not url:
                    logger.warning(f"No Keplr URL configured for {token_symbol}")
                    return None

                page = await self.context.new_page()

                # Set page timeouts
                page.set_default_timeout(self.browser_timeout)
                page.set_default_navigation_timeout(self.browser_timeout)

                # Navigate with timeout and error handling
                try:
                    await page.goto(url, wait_until='networkidle', timeout=self.browser_timeout)
                    await page.wait_for_timeout(3000)  # Wait for dynamic content
                except Exception as nav_error:
                    logger.warning(f"Navigation failed for {token_symbol} (attempt {attempt + 1}): {nav_error}")
                    if attempt < self.max_retries - 1:
                        continue
                    return None

                # XPath selector for APR (from original config)
                apr_selector = "//*[@id='__next']/div[2]/div[2]/div/div[1]/div/div[2]/div/div/div/div[1]/div[2]/p"

                # Try to find APR element
                apr_locator = page.locator(f"xpath={apr_selector}")

                if await apr_locator.count() > 0:
                    apr_text = await apr_locator.first.inner_text()
                    if apr_text:
                        # Extract percentage value
                        apr_match = re.search(r'(\d+\.?\d*)%', apr_text)
                        if apr_match:
                            apr_value = float(apr_match.group(1))
                            self._set_cache(token_symbol, apr_value)
                            logger.info(f"Scraped {token_symbol} APR from Keplr: {apr_value}%")
                            return apr_value

                # Fallback: try alternative selectors
                alternative_selectors = [
                    "text=% APR",
                    "[data-testid*='apr']",
                    ".apr-value",
                    ".staking-apr"
                ]

                for selector in alternative_selectors:
                    try:
                        elements = await page.locator(selector).all()
                        for element in elements:
                            text = await element.inner_text()
                            if text and '%' in text:
                                apr_match = re.search(r'(\d+\.?\d*)%', text)
                                if apr_match:
                                    apr_value = float(apr_match.group(1))
                                    if 0 < apr_value < 100:  # Reasonable APR range
                                        self._set_cache(token_symbol, apr_value)
                                        logger.info(f"Scraped {token_symbol} APR from alternative selector: {apr_value}%")
                                        return apr_value
                    except Exception:
                        continue

                logger.warning(f"Could not find APR for {token_symbol} on Keplr (attempt {attempt + 1})")

                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
                    continue
                return None

            except Exception as e:
                logger.error(f"Error scraping Keplr APR for {token_symbol} (attempt {attempt + 1}): {e}")
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                return None
            finally:
                if page:
                    try:
                        await page.close()
                    except Exception as close_error:
                        logger.error(f"Error closing page: {close_error}")

        # If all retries failed
        logger.error(f"Failed to scrape Keplr APR for {token_symbol} after {self.max_retries} attempts")
        return None

    async def scrape_mintscan_apr(self, token_symbol: str) -> Optional[float]:
        """Scrape APR from Mintscan (alternative source) with retry logic"""
        page = None
        for attempt in range(self.max_retries):
            try:
                mintscan_urls = {
                    'ATOM': 'https://www.mintscan.io/cosmos',
                    'OSMO': 'https://www.mintscan.io/osmosis',
                    'TIA': 'https://www.mintscan.io/celestia',
                    'JUNO': 'https://www.mintscan.io/juno'
                }

                url = mintscan_urls.get(token_symbol)
                if not url:
                    return None

                await self.init_browser()
                page = await self.context.new_page()

                # Set timeouts
                page.set_default_timeout(self.browser_timeout)
                page.set_default_navigation_timeout(self.browser_timeout)

                try:
                    await page.goto(url, wait_until='networkidle', timeout=self.browser_timeout)
                    await page.wait_for_timeout(2000)
                except Exception as nav_error:
                    logger.warning(f"Mintscan navigation failed for {token_symbol} (attempt {attempt + 1}): {nav_error}")
                    if attempt < self.max_retries - 1:
                        continue
                    return None

                # Look for staking APR
                apr_selectors = [
                    "text=/\\d+\\.\\d+%/",
                    "[data-testid*='apr']",
                    ".staking-info",
                    ".apr-percentage"
                ]

                for selector in apr_selectors:
                    try:
                        elements = await page.locator(selector).all()
                        for element in elements:
                            text = await element.inner_text()
                            if text and '%' in text and 'apr' in text.lower():
                                apr_match = re.search(r'(\d+\.?\d*)%', text)
                                if apr_match:
                                    apr_value = float(apr_match.group(1))
                                    if 0 < apr_value < 100:
                                        logger.info(f"Scraped {token_symbol} APR from Mintscan: {apr_value}%")
                                        return apr_value
                    except Exception:
                        continue

                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                return None

            except Exception as e:
                logger.error(f"Error scraping Mintscan APR for {token_symbol} (attempt {attempt + 1}): {e}")
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                return None
            finally:
                if page:
                    try:
                        await page.close()
                    except Exception as close_error:
                        logger.error(f"Error closing Mintscan page: {close_error}")

        logger.error(f"Failed to scrape Mintscan APR for {token_symbol} after {self.max_retries} attempts")
        return None

    async def get_apr_api(self, token_symbol: str) -> Optional[float]:
        """Get APR from API sources (future implementation)"""
        # Placeholder for API-based APR fetching
        # Could be extended to use Cosmos APIs, validator APIs, etc.
        return None

    async def get_token_apr(self, token_symbol: str, chain_name: str = None) -> Optional[float]:
        """Get APR for a token from multiple sources"""
        # Check cache first
        if self._is_cache_valid(token_symbol):
            logger.info(f"Using cached APR for {token_symbol}: {self.cache[token_symbol]}%")
            return self.cache[token_symbol]

        # Try different sources in order of preference
        sources = [
            ('Keplr', self.scrape_keplr_apr),
            ('Mintscan', self.scrape_mintscan_apr),
            ('API', self.get_apr_api)
        ]

        for source_name, scraper_func in sources:
            try:
                logger.info(f"Trying {source_name} for {token_symbol} APR...")

                if source_name == 'Keplr':
                    apr = await scraper_func(token_symbol, chain_name)
                else:
                    apr = await scraper_func(token_symbol)

                if apr is not None and apr > 0:
                    logger.info(f"Successfully got {token_symbol} APR from {source_name}: {apr}%")
                    return apr

            except Exception as e:
                logger.error(f"Error getting APR from {source_name} for {token_symbol}: {e}")
                continue

        logger.warning(f"Could not get APR for {token_symbol} from any source")
        return None

    async def get_multiple_aprs(self, tokens: List[str]) -> Dict[str, Optional[float]]:
        """Get APRs for multiple tokens concurrently with proper resource management"""
        logger.info(f"Fetching APRs for {len(tokens)} tokens...")

        # Create semaphore to limit concurrent requests (reduced for stability)
        semaphore = asyncio.Semaphore(2)  # Max 2 concurrent requests to prevent browser overload

        async def get_single_apr(token):
            async with semaphore:
                try:
                    result = await self.get_token_apr(token)
                    return token, result
                except Exception as e:
                    logger.error(f"Error getting APR for {token}: {e}")
                    return token, None

        # Execute all requests concurrently with timeout
        tasks = [get_single_apr(token) for token in tokens]
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=300  # 5 minute total timeout
            )
        except asyncio.TimeoutError:
            logger.error("APR fetching timed out after 5 minutes")
            # Clean up browser to prevent resource leaks
            await self.cleanup_browser()
            return {token: None for token in tokens}

        apr_dict = {}
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"Error in concurrent APR fetching: {result}")
                continue

            token, apr = result
            apr_dict[token] = apr

        success_count = sum(1 for apr in apr_dict.values() if apr is not None)
        logger.info(f"Successfully fetched APRs for {success_count}/{len(tokens)} tokens")

        # Clean up browser after batch operation to free resources
        await self.cleanup_browser()

        return apr_dict

    def get_cached_aprs(self) -> Dict[str, float]:
        """Get all cached APR values"""
        valid_cache = {}
        current_time = time.time()

        for token, apr in self.cache.items():
            if token in self.cache_expiry and current_time < self.cache_expiry[token]:
                valid_cache[token] = apr

        return valid_cache

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