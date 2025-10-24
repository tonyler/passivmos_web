#!/usr/bin/env python3
"""
=== WALLET ADDRESS ANALYZER ===
Analyzes Cosmos ecosystem wallet addresses for passive income calculations

WHAT IT DOES:
- Takes wallet addresses (cosmos1..., osmo1..., etc)
- Fetches balances and staking data from blockchain APIs
- Calculates passive income projections (daily/monthly/yearly)
- Returns structured analysis data for Discord bot display

AI MODIFICATION GUIDE:
- Add new chains: Update chain_configs dict
- Change API endpoints: Modify rest_endpoints in chain configs
- Add new data sources: Extend the analysis methods
- Modify calculations: Update earnings calculation logic

SUPPORTED CHAINS: Cosmos, Osmosis, Celestia, Juno, Chihuahua, Dymension, Saga, Nolus
DATA SOURCES: Chain REST APIs, cached price/APR data
"""

import asyncio
import aiohttp
import re
import json
import os
from typing import Dict, List, Optional, Tuple, NamedTuple
from dataclasses import dataclass
from pathlib import Path
import logging
from config_loader import config

logger = logging.getLogger(__name__)

# === DATA STRUCTURES ===

@dataclass
class DelegationInfo:
    """Single delegation to a validator"""
    validator_address: str  # Validator's address
    validator_name: str     # Human-readable name
    amount: float          # Delegated amount
    token_symbol: str      # Token type (ATOM, OSMO, etc)
    apr: float = 0.0      # Annual Percentage Rate

@dataclass
class WalletBalance:
    """
    Complete balance info for one address on one chain

    AI MODIFICATION: This structure is returned to Discord bot
    """
    address: str               # Wallet address
    chain: str                # Chain name (cosmos, osmosis, etc)
    token_symbol: str         # Main token symbol
    available_balance: float   # Liquid/available tokens
    delegated_balance: float  # Staked/delegated tokens
    total_balance: float      # available + delegated
    delegations: List[DelegationInfo]  # List of individual delegations

@dataclass
class WalletAnalysis:
    """
    Final analysis result for one wallet address

    AI MODIFICATION: This is what Discord bot receives and displays
    """
    address: str               # Original wallet address
    chain: str                # Detected chain
    balances: List[WalletBalance]  # All token balances found
    total_value_usd: float    # Total USD value
    daily_earnings: float     # Projected daily earnings (USD)
    monthly_earnings: float   # Projected monthly earnings (USD)
    yearly_earnings: float    # Projected yearly earnings (USD)
    error_message: Optional[str] = None  # Error if analysis failed

# === MAIN ANALYZER CLASS ===
class WalletAddressAnalyzer:
    """
    Main class for analyzing Cosmos ecosystem wallet addresses

    USAGE:
    async with WalletAddressAnalyzer() as analyzer:
        results = await analyzer.analyze_addresses_cached(['cosmos1...'])

    AI MODIFICATION GUIDE:
    - Add new chains: Update chain_configs dict below
    - Change API endpoints: Modify rest_endpoints arrays
    - Add new analysis types: Extend analyze methods
    """

    def __init__(self, config_path: Optional[str] = None):
        self.session = None  # aiohttp session (lazy loaded)

        self.chain_configs = config.get_all_network_configs()

    async def __aenter__(self):
        """Async context manager entry"""
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
            headers={'User-Agent': 'PassivMOS4-WalletAnalyzer/1.0'}
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.session:
            await self.session.close()

    def identify_chain_from_address(self, address: str) -> Optional[str]:
        """Identify blockchain from wallet address prefix"""
        for chain, config in self.chain_configs.items():
            if address.startswith(config['bech32_prefix']):
                return chain
        return None

    async def get_wallet_balance(self, address: str, chain: str) -> Optional[WalletBalance]:
        """Get wallet balance and delegations for a specific chain with timeout"""
        try:
            # Apply 15 second timeout per chain
            return await asyncio.wait_for(
                self._get_wallet_balance_internal(address, chain),
                timeout=15.0
            )
        except asyncio.TimeoutError:
            logger.error(f"Timeout fetching balance for {address} on {chain}")
            return None
        except Exception as e:
            logger.error(f"Error analyzing wallet {address} on {chain}: {e}")
            return None

    async def _get_wallet_balance_internal(self, address: str, chain: str) -> Optional[WalletBalance]:
        """Internal wallet balance fetch logic"""
        config = self.chain_configs.get(chain)
        if not config:
            logger.error(f"Unsupported chain: {chain}")
            return None

        # Try multiple endpoints
        for endpoint in config['rest_endpoints']:
            try:
                balance_info = await self._fetch_balance(address, endpoint, config)
                if balance_info is not None:
                    delegations = await self._fetch_delegations(address, endpoint, config)

                    total_delegated = sum(d.amount for d in delegations) if delegations else 0.0

                    return WalletBalance(
                        address=address,
                        chain=chain,
                        token_symbol=config['token_symbol'],
                        available_balance=balance_info,
                        delegated_balance=total_delegated,
                        total_balance=balance_info + total_delegated,
                        delegations=delegations or []
                    )
            except Exception as e:
                logger.warning(f"Failed endpoint {endpoint}: {e}")
                continue

        logger.error(f"All endpoints failed for {chain}")
        return None

    async def _fetch_balance(self, address: str, endpoint: str, config: Dict) -> Optional[float]:
        """Fetch available balance from REST API"""
        try:
            url = f"{endpoint}/cosmos/bank/v1beta1/balances/{address}"

            async with self.session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    balances = data.get('balances', [])

                    # Find native token balance
                    for balance in balances:
                        denom = balance.get('denom', '')
                        amount = balance.get('amount', '0')

                        # Check for native token (usually starts with 'u' or is 'ibc/')
                        if self._is_native_token(denom, config):
                            return float(amount) / (10 ** config['token_decimals'])

                    return 0.0
                else:
                    logger.warning(f"Balance API error: {response.status}")
                    return None

        except Exception as e:
            logger.error(f"Error fetching balance: {e}")
            return None

    async def _fetch_delegations(self, address: str, endpoint: str, config: Dict) -> Optional[List[DelegationInfo]]:
        """Fetch delegation information from REST API"""
        try:
            url = f"{endpoint}/cosmos/staking/v1beta1/delegations/{address}"

            async with self.session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    delegation_responses = data.get('delegation_responses', [])

                    delegations = []
                    for delegation in delegation_responses:
                        delegation_info = delegation.get('delegation', {})
                        balance = delegation.get('balance', {})

                        validator_address = delegation_info.get('validator_address', '')
                        amount = float(balance.get('amount', '0')) / (10 ** config['token_decimals'])

                        if amount > 0:
                            # Get validator name (simplified)
                            validator_name = await self._get_validator_name(validator_address, endpoint)

                            delegations.append(DelegationInfo(
                                validator_address=validator_address,
                                validator_name=validator_name or validator_address[-8:],
                                amount=amount,
                                token_symbol=config['token_symbol']
                            ))

                    return delegations
                else:
                    logger.warning(f"Delegation API error: {response.status}")
                    return []

        except Exception as e:
            logger.error(f"Error fetching delegations: {e}")
            return []

    async def _get_validator_name(self, validator_address: str, endpoint: str) -> Optional[str]:
        """Get validator moniker/name"""
        try:
            url = f"{endpoint}/cosmos/staking/v1beta1/validators/{validator_address}"

            async with self.session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    validator = data.get('validator', {})
                    description = validator.get('description', {})
                    return description.get('moniker', 'Unknown')

        except Exception:
            pass

        return None

    def _is_native_token(self, denom: str, config: Dict) -> bool:
        """Check if denomination is the native token"""
        # Native tokens usually start with 'u' followed by the token name
        # Or they might be the exact token symbol in lowercase
        token_symbol = config['token_symbol'].lower()

        # Common patterns
        if denom == f"u{token_symbol}":
            return True
        if denom == token_symbol:
            return True
        if denom == "uatom" and token_symbol == "atom":
            return True
        if denom == "uosmo" and token_symbol == "osmo":
            return True
        if denom == "utia" and token_symbol == "tia":
            return True
        if denom == "ujuno" and token_symbol == "juno":
            return True
        if denom == "uhuahua" and token_symbol == "huahua":
            return True
        if denom == "adym" and token_symbol == "dym":
            return True

        return False

    async def analyze_addresses(self, addresses: List[str], price_fetcher=None, default_aprs: Dict[str, float] = None) -> List[WalletAnalysis]:
        """Analyze multiple wallet addresses"""
        if not addresses:
            return []

        logger.info(f"Analyzing {len(addresses)} wallet addresses...")

        results = []

        # Process addresses concurrently with rate limiting
        semaphore = asyncio.Semaphore(5)  # Max 5 concurrent requests

        async def analyze_single_address(address):
            async with semaphore:
                return await self._analyze_single_address(address, price_fetcher, default_aprs)

        tasks = [analyze_single_address(addr.strip()) for addr in addresses if addr.strip()]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Filter out exceptions
        valid_results = []
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"Error analyzing address: {result}")
                continue
            if result:
                valid_results.append(result)

        logger.info(f"Successfully analyzed {len(valid_results)}/{len(addresses)} addresses")
        return valid_results

    async def analyze_addresses_cached(self, addresses: List[str], cache_manager) -> List[WalletAnalysis]:
        """Analyze multiple wallet addresses using cached data"""
        if not addresses:
            return []

        logger.info(f"Analyzing {len(addresses)} wallet addresses using cached data...")

        results = []

        # Process addresses concurrently with rate limiting
        semaphore = asyncio.Semaphore(10)  # Higher limit since we're using cache

        async def analyze_single_address_cached(address):
            async with semaphore:
                return await self._analyze_single_address_cached(address, cache_manager)

        tasks = [analyze_single_address_cached(addr.strip()) for addr in addresses if addr.strip()]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Filter out exceptions
        valid_results = []
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"Error analyzing address: {result}")
                continue
            if result:
                valid_results.append(result)

        logger.info(f"Successfully analyzed {len(valid_results)}/{len(addresses)} addresses using cache")
        return valid_results

    async def _analyze_single_address_cached(self, address: str, cache_manager) -> Optional[WalletAnalysis]:
        """Analyze a single wallet address using cached data"""
        try:
            # Identify chain from address
            chain = self.identify_chain_from_address(address)
            if not chain:
                return WalletAnalysis(
                    address=address,
                    chain="unknown",
                    balances=[],
                    total_value_usd=0.0,
                    daily_earnings=0.0,
                    monthly_earnings=0.0,
                    yearly_earnings=0.0,
                    error_message=f"Could not identify blockchain for address {address}"
                )

            # Get wallet balance and delegations
            wallet_balance = await self.get_wallet_balance(address, chain)
            if not wallet_balance:
                return WalletAnalysis(
                    address=address,
                    chain=chain,
                    balances=[],
                    total_value_usd=0.0,
                    daily_earnings=0.0,
                    monthly_earnings=0.0,
                    yearly_earnings=0.0,
                    error_message=f"Could not fetch data for {address}"
                )

            # Get cached price and APR
            token_symbol = wallet_balance.token_symbol
            price_usd = 0.0
            apr = 15.0  # Default APR

            # Get cached price
            try:
                from data_cache import get_cached_price, get_cached_apr
                cached_price = get_cached_price(token_symbol)
                if cached_price:
                    price_usd = cached_price.price_usd
                    logger.debug(f"Using cached price for {token_symbol}: ${price_usd}")

                # Get cached APR
                cached_apr = get_cached_apr(token_symbol)
                if cached_apr:
                    apr = cached_apr.apr
                    logger.debug(f"Using cached APR for {token_symbol}: {apr}%")

            except Exception as e:
                logger.warning(f"Could not get cached data for {token_symbol}: {e}")

            # Update delegations with APR
            for delegation in wallet_balance.delegations:
                delegation.apr = apr

            # Calculate values
            total_value_usd = wallet_balance.total_balance * price_usd
            yearly_earnings = wallet_balance.delegated_balance * (apr / 100) * price_usd
            daily_earnings = yearly_earnings / 365
            monthly_earnings = yearly_earnings / 12

            return WalletAnalysis(
                address=address,
                chain=chain,
                balances=[wallet_balance],
                total_value_usd=total_value_usd,
                daily_earnings=daily_earnings,
                monthly_earnings=monthly_earnings,
                yearly_earnings=yearly_earnings
            )

        except Exception as e:
            logger.error(f"Error analyzing address {address} with cache: {e}")
            return WalletAnalysis(
                address=address,
                chain="error",
                balances=[],
                total_value_usd=0.0,
                daily_earnings=0.0,
                monthly_earnings=0.0,
                yearly_earnings=0.0,
                error_message=str(e)
            )

    async def _analyze_single_address(self, address: str, price_fetcher=None, default_aprs: Dict[str, float] = None) -> Optional[WalletAnalysis]:
        """Analyze a single wallet address"""
        try:
            # Identify chain from address
            chain = self.identify_chain_from_address(address)
            if not chain:
                return WalletAnalysis(
                    address=address,
                    chain="unknown",
                    balances=[],
                    total_value_usd=0.0,
                    daily_earnings=0.0,
                    monthly_earnings=0.0,
                    yearly_earnings=0.0,
                    error_message=f"Could not identify blockchain for address {address}"
                )

            # Get wallet balance and delegations
            wallet_balance = await self.get_wallet_balance(address, chain)
            if not wallet_balance:
                return WalletAnalysis(
                    address=address,
                    chain=chain,
                    balances=[],
                    total_value_usd=0.0,
                    daily_earnings=0.0,
                    monthly_earnings=0.0,
                    yearly_earnings=0.0,
                    error_message=f"Could not fetch data for {address}"
                )

            # Calculate USD value and earnings
            token_symbol = wallet_balance.token_symbol
            price_usd = 0.0
            apr = default_aprs.get(token_symbol, 15.0) if default_aprs else 15.0  # Default 15% APR

            # Get current price if price_fetcher is available
            if price_fetcher:
                try:
                    price_data = await price_fetcher.get_price(token_symbol)
                    if price_data:
                        price_usd = price_data.price_usd
                except Exception as e:
                    logger.warning(f"Could not get price for {token_symbol}: {e}")

            # Update delegations with APR
            for delegation in wallet_balance.delegations:
                delegation.apr = apr

            # Calculate values
            total_value_usd = wallet_balance.total_balance * price_usd
            yearly_earnings = wallet_balance.delegated_balance * (apr / 100) * price_usd
            daily_earnings = yearly_earnings / 365
            monthly_earnings = yearly_earnings / 12

            return WalletAnalysis(
                address=address,
                chain=chain,
                balances=[wallet_balance],
                total_value_usd=total_value_usd,
                daily_earnings=daily_earnings,
                monthly_earnings=monthly_earnings,
                yearly_earnings=yearly_earnings
            )

        except Exception as e:
            logger.error(f"Error analyzing address {address}: {e}")
            return WalletAnalysis(
                address=address,
                chain="error",
                balances=[],
                total_value_usd=0.0,
                daily_earnings=0.0,
                monthly_earnings=0.0,
                yearly_earnings=0.0,
                error_message=str(e)
            )

# Example usage
async def test_wallet_analyzer():
    """Test the wallet analyzer"""
    addresses = [
        "cosmos1qnsxa5chxj87mvm9jxqnyr9pdlp324mp33pxuu",
        "osmo19c7rnyq3x62jyfym0zfp33hr9u4m8zwg8gafd0"
    ]

    async with WalletAddressAnalyzer() as analyzer:
        results = await analyzer.analyze_addresses(addresses)

        for result in results:
            print(f"\nAddress: {result.address}")
            print(f"Chain: {result.chain}")
            print(f"Total Value: ${result.total_value_usd:.2f}")
            print(f"Daily Earnings: ${result.daily_earnings:.2f}")

if __name__ == "__main__":
    asyncio.run(test_wallet_analyzer())