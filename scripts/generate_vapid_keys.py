"""Generate a VAPID key pair for Web Push notifications.

Prints single-line base64url values ready for .env:
    VAPID_PRIVATE_KEY (raw 32-byte EC private key, accepted by pywebpush)
    VAPID_PUBLIC_KEY  (uncompressed X9.62 point, used by the browser client)

Usage: make push-keys
"""

import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def main() -> None:
    key = ec.generate_private_key(ec.SECP256R1())
    private_raw = key.private_numbers().private_value.to_bytes(32, "big")
    public_raw = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    print("Add to your .env:")
    print()
    print(f"VAPID_PRIVATE_KEY={b64url(private_raw)}")
    print(f"VAPID_PUBLIC_KEY={b64url(public_raw)}")
    print("VAPID_CLAIMS_EMAIL=<your-email>")


if __name__ == "__main__":
    main()
