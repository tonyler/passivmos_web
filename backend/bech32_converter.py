#!/usr/bin/env python3
"""
Bech32 Address Converter
Converts addresses between different Cosmos chains using the same public key
"""
import logging
from typing import List, Dict, Optional
from bech32 import bech32_decode, bech32_encode, convertbits

logger = logging.getLogger(__name__)

class Bech32Converter:
    """Convert addresses between different bech32 prefixes"""

    # Supported chain prefixes
    CHAIN_PREFIXES = {
        'cosmos': 'cosmos',
        'osmosis': 'osmo',
        'celestia': 'celestia',
        'juno': 'juno',
        'chihuahua': 'chihuahua',
        'dymension': 'dym',
        'saga': 'saga',
        'nolus': 'nolus',
        # Note: Cardano uses different address format, not bech32 compatible
    }

    @staticmethod
    def decode_address(address: str) -> Optional[bytes]:
        """
        Decode a bech32 address to get the raw data

        Args:
            address: Bech32 encoded address (e.g., cosmos1abc...)

        Returns:
            Raw address data as bytes, or None if decode fails
        """
        try:
            hrp, data = bech32_decode(address)
            if hrp is None or data is None:
                logger.error(f"Failed to decode address: {address}")
                return None

            # Convert from 5-bit to 8-bit encoding
            decoded = convertbits(data, 5, 8, False)
            if decoded is None:
                logger.error(f"Failed to convert bits for address: {address}")
                return None

            return bytes(decoded)

        except Exception as e:
            logger.error(f"Error decoding address {address}: {e}")
            return None

    @staticmethod
    def encode_address(data: bytes, prefix: str) -> Optional[str]:
        """
        Encode raw address data with a new prefix

        Args:
            data: Raw address data
            prefix: New bech32 prefix (e.g., 'osmo', 'juno')

        Returns:
            Bech32 encoded address with new prefix, or None if encode fails
        """
        try:
            # Convert from 8-bit to 5-bit encoding
            converted = convertbits(data, 8, 5, True)
            if converted is None:
                logger.error(f"Failed to convert bits for encoding with prefix {prefix}")
                return None

            # Encode with new prefix
            encoded = bech32_encode(prefix, converted)
            return encoded

        except Exception as e:
            logger.error(f"Error encoding address with prefix {prefix}: {e}")
            return None

    @classmethod
    def convert_address(cls, address: str, new_prefix: str) -> Optional[str]:
        """
        Convert an address to a different chain prefix

        Args:
            address: Original address (e.g., cosmos1abc...)
            new_prefix: Target chain prefix (e.g., 'osmo')

        Returns:
            Converted address, or None if conversion fails

        Example:
            convert_address('cosmos1abc...', 'osmo') -> 'osmo1abc...'
        """
        # Decode original address
        data = cls.decode_address(address)
        if data is None:
            return None

        # Encode with new prefix
        new_address = cls.encode_address(data, new_prefix)
        return new_address

    @classmethod
    def get_all_chain_addresses(cls, address: str) -> Dict[str, str]:
        """
        Convert an address to all supported chain variants

        Args:
            address: Original address from any supported chain

        Returns:
            Dictionary mapping chain name to converted address

        Example:
            Input: 'cosmos1abc...'
            Output: {
                'cosmos': 'cosmos1abc...',
                'osmosis': 'osmo1abc...',
                'celestia': 'celestia1abc...',
                ...
            }
        """
        # Decode the original address
        data = cls.decode_address(address)
        if data is None:
            logger.error(f"Could not decode address: {address}")
            return {}

        # Convert to all chain prefixes
        all_addresses = {}

        for chain_name, prefix in cls.CHAIN_PREFIXES.items():
            converted = cls.encode_address(data, prefix)
            if converted:
                all_addresses[chain_name] = converted
                logger.debug(f"Converted to {chain_name}: {converted}")
            else:
                logger.warning(f"Failed to convert address to {chain_name}")

        return all_addresses

    @classmethod
    def detect_chain(cls, address: str) -> Optional[str]:
        """
        Detect which chain an address belongs to

        Args:
            address: Bech32 address

        Returns:
            Chain name, or None if not recognized
        """
        try:
            hrp, _ = bech32_decode(address)
            if hrp is None:
                return None

            # Find matching chain
            for chain_name, prefix in cls.CHAIN_PREFIXES.items():
                if hrp == prefix:
                    return chain_name

            return None

        except Exception as e:
            logger.error(f"Error detecting chain for {address}: {e}")
            return None


# Example usage and tests
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Test with a sample address
    test_address = "cosmos1qnsxa5chxj87mvm9jxqnyr9pdlp324mp33pxuu"

    print(f"🧪 Testing Bech32 Converter with: {test_address}\n")

    # Detect chain
    chain = Bech32Converter.detect_chain(test_address)
    print(f"Detected chain: {chain}")

    # Convert to all chains
    print("\n📡 Converting to all supported chains:")
    all_addresses = Bech32Converter.get_all_chain_addresses(test_address)

    for chain_name, address in all_addresses.items():
        print(f"  {chain_name:12} → {address}")

    # Test individual conversion
    print("\n🔄 Testing individual conversion:")
    osmo_address = Bech32Converter.convert_address(test_address, 'osmo')
    print(f"  Osmosis: {osmo_address}")

    # Convert back
    cosmos_address = Bech32Converter.convert_address(osmo_address, 'cosmos')
    print(f"  Back to Cosmos: {cosmos_address}")
    print(f"  Match: {cosmos_address == test_address}")

    print("\n✅ Bech32 converter test complete!")
