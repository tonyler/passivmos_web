#!/usr/bin/env python3
"""
APR Fetcher for Passive Income Calculator
Primary: chain REST APIs (annual_provisions / bonded_tokens)
Fallback: Keplr page scraping for chains without standard mint module
"""

import asyncio
import aiohttp
import re
import json
import time
from typing import Dict, Optional, List
from pathlib import Path
import logging
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from config_loader import config

logger = logging.getLogger(__name__)

_global_fetching_lock = asyncio.Lock()

# Tokens that need Keplr scraping (no standard mint module)
KEPLR_SCRAPE_TOKENS = {'OSMO', 'DYM', 'NLS'}


class APRScraper:
    """APR fetcher: chain REST APIs primary, Keplr scraping fallback"""

    def __init__(self, cache_dir: str = None):
        self.session = None
        self.browser = None
        self.playwright = None
        self.context = None

        if cache_dir is None:
            # Resolve relative to project root to avoid CWD-dependent cache misses
            cache_dir = Path(__file__).parent.parent / "data" / "cache"
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.cache_dir / "apr_cache.json"

        self.memory_cache = {}
        self.cache_timestamps = {}
        self.fresh_duration = 600     # 10 minutes
        self.stale_duration = 86400   # 24 hours

        self.config_fallbacks = {}
        for symbol in config.get_enabled_tokens():
            token_config = config.get_token_config(symbol)
            if token_config:
                self.config_fallbacks[symbol] = token_config.get('fallback_apr', 10.0)

        self._load_cache_from_disk()

    def _load_cache_from_disk(self):
        if not self.cache_file.exists():
            return
        try:
            with open(self.cache_file, 'r') as f:
                data = json.load(f)
                self.memory_cache = data.get('cache', {})
                raw_timestamps = data.get('timestamps', {})
                self.cache_timestamps = {k: float(v) for k, v in raw_timestamps.items()}
            logger.info(f"Loaded {len(self.memory_cache)} cached APRs from disk")
        except Exception as e:
            logger.error(f"Error loading cache from disk: {e}")

    def _save_cache_to_disk(self):
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
        if token not in self.memory_cache or token not in self.cache_timestamps:
            return False
        age = time.time() - self.cache_timestamps[token]
        return age < self.fresh_duration

    def _is_cache_stale(self, token: str) -> bool:
        if token not in self.memory_cache or token not in self.cache_timestamps:
            return False
        age = time.time() - self.cache_timestamps[token]
        return age < self.stale_duration

    def _get_cache_age(self, token: str) -> Optional[float]:
        if token not in self.cache_timestamps:
            return None
        return (time.time() - self.cache_timestamps[token]) / 3600

    def _set_cache(self, token: str, apr: float):
        self.memory_cache[token] = apr
        self.cache_timestamps[token] = time.time()
        self._save_cache_to_disk()
        logger.info(f"{token}: Cached {apr}% APR")

    def _get_cached_or_fallback(self, token: str) -> float:
        if self._is_cache_fresh(token):
            age = self._get_cache_age(token)
            logger.info(f"{token}: Using fresh cache ({age:.1f}h old)")
            return self.memory_cache[token]

        if self._is_cache_stale(token):
            age = self._get_cache_age(token)
            logger.warning(f"{token}: Using stale cache ({age:.1f}h old)")
            return self.memory_cache[token]

        fallback = self.config_fallbacks.get(token, 0.0)
        if fallback <= 0:
            # Defensive: read from config directly in case config_fallbacks is stale/empty
            token_config = config.get_token_config(token)
            if token_config:
                fallback = token_config.get('fallback_apr', 0.0)
        if fallback > 0:
            logger.warning(f"{token}: Using config fallback APR: {fallback}%")
            return fallback

        logger.error(f"{token}: No cache or fallback available, returning 0")
        return 0.0

    async def __aenter__(self):
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=15),
            headers={'User-Agent': 'PassivMOS/1.0'}
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.cleanup_browser()
        if self.session:
            await self.session.close()

    async def cleanup_browser(self):
        # Close in strict order and always continue so a single close failure
        # does not leak the underlying Playwright driver process.
        if self.context:
            try:
                await self.context.close()
            except Exception as e:
                logger.warning(f"Error closing browser context: {e}")
            finally:
                self.context = None

        if self.browser:
            try:
                await self.browser.close()
            except Exception as e:
                logger.warning(f"Error closing browser: {e}")
            finally:
                self.browser = None

        if self.playwright:
            try:
                await self.playwright.stop()
            except Exception as e:
                logger.warning(f"Error stopping Playwright: {e}")
            finally:
                self.playwright = None

    async def _init_browser(self):
        if self.browser:
            return
        from playwright.async_api import async_playwright
        playwright = None
        browser = None
        context = None
        try:
            playwright = await async_playwright().start()
            browser = await playwright.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu']
            )
            context = await browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                viewport={'width': 1280, 'height': 720},
                ignore_https_errors=True
            )
            context.set_default_timeout(30000)
            context.set_default_navigation_timeout(30000)

            # Publish handles only after full successful init to avoid leaks.
            self.playwright = playwright
            self.browser = browser
            self.context = context
        except Exception:
            if context:
                try:
                    await context.close()
                except Exception:
                    pass
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass
            if playwright:
                try:
                    await playwright.stop()
                except Exception:
                    pass
            raise

    async def _fetch_json(self, url: str) -> Optional[dict]:
        try:
            async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    return await resp.json()
                logger.warning(f"HTTP {resp.status} from {url}")
        except Exception as e:
            logger.warning(f"Failed to fetch {url}: {e}")
        return None

    async def fetch_chain_apr(self, token_symbol: str) -> Optional[float]:
        """Fetch staking APR from chain REST APIs."""
        token_config = config.get_token_config(token_symbol)
        if not token_config:
            return None

        if token_config.get('skip_apr_scraping', False):
            return token_config.get('fallback_apr', 0.0)

        endpoints = token_config.get('rest_endpoints', [])
        if not endpoints:
            return None

        for endpoint in endpoints:
            endpoint = endpoint.rstrip('/')
            try:
                provisions_data, pool_data, params_data = await asyncio.gather(
                    self._fetch_json(f"{endpoint}/cosmos/mint/v1beta1/annual_provisions"),
                    self._fetch_json(f"{endpoint}/cosmos/staking/v1beta1/pool"),
                    self._fetch_json(f"{endpoint}/cosmos/distribution/v1beta1/params"),
                )

                if not provisions_data:
                    continue
                annual_provisions_str = provisions_data.get('annual_provisions', '')
                if not annual_provisions_str:
                    continue
                annual_provisions = float(annual_provisions_str)

                if not pool_data or 'pool' not in pool_data:
                    continue
                bonded_tokens = float(pool_data['pool'].get('bonded_tokens', '0'))
                if bonded_tokens <= 0:
                    continue

                community_tax = 0.0
                if params_data and 'params' in params_data:
                    community_tax = float(params_data['params'].get('community_tax', '0'))

                apr = (annual_provisions / bonded_tokens) * (1 - community_tax) * 100

                if 0 < apr < 200:
                    rounded = round(apr, 2)
                    self._set_cache(token_symbol, rounded)
                    logger.info(f"{token_symbol}: Fetched {rounded}% APR from chain API")
                    return rounded

                logger.warning(f"{token_symbol}: Calculated APR {apr:.2f}% out of range")

            except Exception as e:
                logger.warning(f"{token_symbol}: Error fetching from {endpoint}: {e}")
                continue

        return None

    async def scrape_keplr_apr(self, token_symbol: str) -> Optional[float]:
        """Scrape APR from Keplr wallet page. Looks for 'Staking APR X.XX%' text."""
        token_config = config.get_token_config(token_symbol)
        if not token_config:
            return None

        keplr_url = token_config.get('keplr_url')
        if not keplr_url:
            return None

        for attempt in range(2):
            page = None
            try:
                await self._init_browser()
                page = await self.context.new_page()

                await page.goto(keplr_url, wait_until='networkidle', timeout=30000)
                await page.wait_for_timeout(4000)

                # Look for "Staking APR X.XX%" text in <p> elements
                elements = await page.locator("p").all()
                for el in elements:
                    text = await el.inner_text()
                    match = re.search(r'Staking APR\s+(\d+\.?\d*)%', text)
                    if match:
                        apr_value = float(match.group(1))
                        if 0 < apr_value < 200:
                            self._set_cache(token_symbol, apr_value)
                            logger.info(f"{token_symbol}: Scraped {apr_value}% from Keplr")
                            return apr_value

                # Fallback: any element with "APR X.XX%"
                all_elements = await page.locator("span, div, p").all()
                for el in all_elements:
                    try:
                        text = await el.inner_text()
                        if 'APR' in text and '%' in text and len(text) < 30:
                            match = re.search(r'(\d+\.?\d*)%', text)
                            if match:
                                apr_value = float(match.group(1))
                                if 0 < apr_value < 100:
                                    self._set_cache(token_symbol, apr_value)
                                    logger.info(f"{token_symbol}: Scraped {apr_value}% from Keplr (fallback selector)")
                                    return apr_value
                    except Exception:
                        continue

                logger.warning(f"{token_symbol}: Could not find APR on Keplr (attempt {attempt + 1})")
                if attempt == 0:
                    await asyncio.sleep(2)

            except Exception as e:
                logger.error(f"{token_symbol}: Keplr scraping error (attempt {attempt + 1}): {e}")
                if attempt == 0:
                    await asyncio.sleep(2)
            finally:
                if page:
                    try:
                        await page.close()
                    except Exception:
                        pass

        return None

    async def get_multiple_aprs(self, tokens: List[str]) -> Dict[str, float]:
        """Get APRs for multiple tokens. Chain API first, Keplr scraping for select tokens."""
        logger.info(f"Fetching APRs for {len(tokens)} tokens...")

        apr_dict = {}
        tokens_to_fetch = []

        for token in tokens:
            token = token.upper()
            if self._is_cache_fresh(token):
                apr_dict[token] = self._get_cached_or_fallback(token)
            else:
                tokens_to_fetch.append(token)

        if not tokens_to_fetch:
            logger.info("All tokens have fresh cache")
            return apr_dict

        if _global_fetching_lock.locked():
            logger.info("Another fetch in progress, using cache/fallback...")
            async with _global_fetching_lock:
                for token in tokens_to_fetch:
                    apr_dict[token] = self._get_cached_or_fallback(token)
                return apr_dict

        async with _global_fetching_lock:
            # Phase 1: Try chain REST API for all tokens in parallel
            chain_api_tokens = [t for t in tokens_to_fetch if t not in KEPLR_SCRAPE_TOKENS]
            keplr_tokens = [t for t in tokens_to_fetch if t in KEPLR_SCRAPE_TOKENS]

            if chain_api_tokens:
                logger.info(f"Chain API fetch: {', '.join(chain_api_tokens)}")
                tasks = {t: self.fetch_chain_apr(t) for t in chain_api_tokens}
                results = await asyncio.gather(*tasks.values(), return_exceptions=True)

                for token, result in zip(tasks.keys(), results):
                    if isinstance(result, Exception):
                        logger.error(f"{token}: Chain API exception: {result}")
                        apr_dict[token] = self._get_cached_or_fallback(token)
                    elif result is not None:
                        apr_dict[token] = result
                    else:
                        apr_dict[token] = self._get_cached_or_fallback(token)

            # Phase 2: Keplr scraping for OSMO, DYM, NLS (sequential - shared browser)
            if keplr_tokens:
                logger.info(f"Keplr scrape: {', '.join(keplr_tokens)}")
                try:
                    for token in keplr_tokens:
                        try:
                            apr = await asyncio.wait_for(
                                self.scrape_keplr_apr(token),
                                timeout=45.0
                            )
                            if apr is not None:
                                apr_dict[token] = apr
                            else:
                                apr_dict[token] = self._get_cached_or_fallback(token)
                        except asyncio.TimeoutError:
                            logger.error(f"{token}: Keplr scraping timed out")
                            apr_dict[token] = self._get_cached_or_fallback(token)
                        except Exception as e:
                            logger.error(f"{token}: Keplr scraping failed: {e}")
                            apr_dict[token] = self._get_cached_or_fallback(token)
                finally:
                    await self.cleanup_browser()

        for token in tokens:
            token = token.upper()
            if token not in apr_dict:
                apr_dict[token] = self._get_cached_or_fallback(token)

        logger.info(f"Returned APRs for {len(apr_dict)}/{len(tokens)} tokens")
        return apr_dict


async def test_apr_scraper():
    async with APRScraper() as scraper:
        tokens = ['ATOM', 'OSMO', 'TIA', 'JUNO', 'HUAHUA', 'DYM', 'SAGA', 'NLS']
        aprs = await scraper.get_multiple_aprs(tokens)
        print("\nAll APRs:")
        for token, apr in aprs.items():
            print(f"  {token}: {apr}%")

if __name__ == "__main__":
    asyncio.run(test_apr_scraper())
