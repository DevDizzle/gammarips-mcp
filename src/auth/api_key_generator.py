"""
API Key Generator for GammaRips TaaS
Generates secure API keys for user authentication
"""

import hashlib
import secrets


def generate_api_key() -> str:
    """Generate a secure API key.

    Format: ps_live_{32_hex_chars}

    Returns:
        str: A secure API key
    """
    # Generate 32 random bytes and convert to hex
    random_hex = secrets.token_hex(16)  # 16 bytes = 32 hex chars

    # Format: ps_live_{random_hex}
    api_key = f"ps_live_{random_hex}"

    return api_key


def hash_api_key(api_key: str) -> str:
    """Hash an API key for secure storage.

    Args:
        api_key: The API key to hash

    Returns:
        str: SHA-256 hash of the API key
    """
    return hashlib.sha256(api_key.encode()).hexdigest()


def main():
    """Generate and display a new API key (for testing)."""
    api_key = generate_api_key()
    api_key_hash = hash_api_key(api_key)

    print("Generated API Key:")
    print(f"  Key: {api_key}")
    print(f"  Hash: {api_key_hash}")
    print()
    print("Store the hash in Firestore and give the key to the user.")
    print("The key should be kept secret and never stored in plain text.")


if __name__ == "__main__":
    main()
