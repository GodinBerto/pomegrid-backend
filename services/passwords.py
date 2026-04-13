import bcrypt
from werkzeug.security import check_password_hash


_BCRYPT_PREFIXES = ("$2a$", "$2b$", "$2y$")


def hash_password(password):
    normalized = str(password or "")
    if not normalized:
        raise ValueError("Password is required")
    return bcrypt.hashpw(normalized.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(stored_hash, password):
    normalized_hash = str(stored_hash or "").strip()
    normalized_password = str(password or "")
    if not normalized_hash or not normalized_password:
        return False

    if normalized_hash.startswith(_BCRYPT_PREFIXES):
        try:
            return bcrypt.checkpw(
                normalized_password.encode("utf-8"),
                normalized_hash.encode("utf-8"),
            )
        except ValueError:
            return False

    try:
        return check_password_hash(normalized_hash, normalized_password)
    except ValueError:
        return False
