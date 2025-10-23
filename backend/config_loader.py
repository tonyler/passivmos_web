#!/usr/bin/env python3
"""
Central Configuration Loader
ALL app configuration comes from this single file
"""
import json
from pathlib import Path
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)

class ConfigLoader:
    """Loads and provides access to the master config.json"""

    _instance = None
    _config = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ConfigLoader, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if self._config is None:
            self.load_config()

    def load_config(self, config_path: Optional[str] = None):
        """Load configuration from config.json"""
        if config_path is None:
            # Look for config.json in project root
            project_root = Path(__file__).parent.parent
            config_path = project_root / 'config.json'
        else:
            config_path = Path(config_path)

        try:
            with open(config_path, 'r') as f:
                self._config = json.load(f)
            logger.info(f"Configuration loaded from {config_path}")
        except FileNotFoundError:
            logger.error(f"Configuration file not found: {config_path}")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in configuration file: {e}")
            raise

    def get_enabled_tokens(self) -> List[str]:
        """Get list of enabled token symbols"""
        if not self._config:
            return []

        enabled = []
        for symbol, config in self._config.get('tokens', {}).items():
            if config.get('enabled', False):
                enabled.append(symbol)

        return enabled

    def get_token_config(self, symbol: str) -> Optional[Dict]:
        """Get configuration for a specific token"""
        if not self._config:
            return None

        return self._config.get('tokens', {}).get(symbol.upper())

    def is_token_enabled(self, symbol: str) -> bool:
        """Check if a token is enabled"""
        config = self.get_token_config(symbol)
        return config.get('enabled', False) if config else False

    def get_all_tokens(self, enabled_only: bool = True) -> Dict[str, Dict]:
        """Get all token configurations"""
        if not self._config:
            return {}

        tokens = self._config.get('tokens', {})

        if enabled_only:
            return {
                symbol: config
                for symbol, config in tokens.items()
                if config.get('enabled', False)
            }

        return tokens

    def get_network_config(self, symbol: str) -> Dict:
        """Get network configuration for wallet analyzer"""
        token = self.get_token_config(symbol)
        if not token:
            return {}

        return {
            'rest_endpoints': token.get('rest_endpoints', []),
            'token_symbol': token.get('symbol'),
            'token_decimals': token.get('decimals', 6),
            'bech32_prefix': token.get('bech32_prefix')
        }

    def get_all_network_configs(self) -> Dict[str, Dict]:
        """Get all network configs for wallet analyzer"""
        configs = {}
        for symbol in self.get_enabled_tokens():
            token = self.get_token_config(symbol)
            if token:
                chain_name = token.get('chain_name')
                configs[chain_name] = {
                    'rest_endpoints': token.get('rest_endpoints', []),
                    'token_symbol': token.get('symbol'),
                    'token_decimals': token.get('decimals', 6),
                    'bech32_prefix': token.get('bech32_prefix')
                }
        return configs

    def get_apr_config(self, symbol: str) -> Dict:
        """Get APR configuration for a token"""
        token = self.get_token_config(symbol)
        if not token:
            return {}

        return {
            'fallback_apr': token.get('fallback_apr', 10.0),
            'source': 'scraper',
            'scraper_source': 'keplr',
            'description': f"{token.get('name')} staking APR"
        }

    def get_all_apr_configs(self) -> Dict[str, Dict]:
        """Get all APR configs"""
        aprs = {}
        for symbol in self.get_enabled_tokens():
            aprs[symbol] = self.get_apr_config(symbol)
        return aprs

    def get_keplr_urls(self) -> Dict[str, str]:
        """Get Keplr URLs for APR scraping"""
        urls = {}
        for symbol in self.get_enabled_tokens():
            token = self.get_token_config(symbol)
            if token and 'keplr_url' in token:
                urls[symbol] = token['keplr_url']
        return urls

    def get_token_denoms(self) -> Dict[str, str]:
        """Get IBC denoms for price fetching"""
        denoms = {}
        for symbol in self.get_enabled_tokens():
            token = self.get_token_config(symbol)
            if token and 'ibc_denom' in token:
                denoms[symbol] = token['ibc_denom']
        return denoms

    def get_settings(self) -> Dict:
        """Get global settings"""
        return self._config.get('settings', {})

    def is_scraping_enabled(self) -> bool:
        """Check if APR scraping is enabled"""
        settings = self.get_settings()
        return settings.get('scraping', {}).get('enabled', True)

    def is_price_api_enabled(self) -> bool:
        """Check if price API is enabled"""
        settings = self.get_settings()
        return settings.get('price_api', {}).get('enabled', True)

    def is_wallet_analysis_enabled(self) -> bool:
        """Check if wallet analysis is enabled"""
        settings = self.get_settings()
        return settings.get('wallet_analysis', {}).get('enabled', True)

    def reload(self):
        """Reload configuration from disk"""
        self._config = None
        self.load_config()


# Global config instance
config = ConfigLoader()


# Convenience functions
def get_enabled_tokens() -> List[str]:
    """Get list of enabled token symbols"""
    return config.get_enabled_tokens()


def get_token_config(symbol: str) -> Optional[Dict]:
    """Get configuration for a specific token"""
    return config.get_token_config(symbol)


def is_token_enabled(symbol: str) -> bool:
    """Check if a token is enabled"""
    return config.is_token_enabled(symbol)
