"""Fernet encryption for secrets stored in the database."""

from cryptography.fernet import Fernet, InvalidToken


class SecretBox:
    def __init__(self, fernet_key: str) -> None:
        self._fernet = Fernet(fernet_key.encode())

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._fernet.decrypt(ciphertext.encode()).decode()
        except InvalidToken as exc:
            raise ValueError("Failed to decrypt secret — check FERNET_KEY") from exc
