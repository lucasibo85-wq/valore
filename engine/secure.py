"""Scrittura dei file per l'app, cifrati se e' impostato un codice d'accesso.

Con il segreto APP_PASSWORD su GitHub i dati vengono cifrati (AES-256-GCM, chiave derivata
dal codice con PBKDF2-SHA256): chi apre il sito senza codice non vede nulla, nemmeno
scaricando i file. Senza codice i file restano in chiaro come prima.
"""
import base64
import json
import os

ITER = 150000


def _b64(b):
    return base64.b64encode(b).decode()


def write_outputs(out_dir, files):
    os.makedirs(out_dir, exist_ok=True)
    pw = os.environ.get("APP_PASSWORD", "").strip()
    if not pw:
        for name, obj in files.items():
            _write(os.path.join(out_dir, name + ".json"), json.dumps(obj, ensure_ascii=False, separators=(",", ":")))
            _rm(os.path.join(out_dir, name + ".enc"))
        return
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    salt = os.urandom(16)
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITER).derive(pw.encode("utf-8"))
    aes = AESGCM(key)
    for name, obj in files.items():
        iv = os.urandom(12)
        data = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ct = aes.encrypt(iv, data, None)
        env = {"v": 1, "iter": ITER, "salt": _b64(salt), "iv": _b64(iv), "ct": _b64(ct)}
        _write(os.path.join(out_dir, name + ".enc"), json.dumps(env))
        _rm(os.path.join(out_dir, name + ".json"))
    # file "spia" in chiaro, senza dati: dice all'app che serve il codice
    _write(os.path.join(out_dir, "lock.json"), json.dumps({"locked": True}))


def _write(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def _rm(path):
    try:
        os.remove(path)
    except OSError:
        pass
