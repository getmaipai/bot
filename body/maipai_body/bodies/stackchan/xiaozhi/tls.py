"""Local TLS certificate helpers for the StackChan xiaozhi service."""

from __future__ import annotations

import ipaddress
import shutil
import ssl
import subprocess
from pathlib import Path


def server_ssl_context(
    cert_path: str | None,
    key_path: str | None,
) -> ssl.SSLContext | None:
    """Create a TLS server context, or return None when TLS is not configured."""
    if bool(cert_path) != bool(key_path):
        raise ValueError(
            "MAIPAI_XIAOZHI_TLS_CERT and MAIPAI_XIAOZHI_TLS_KEY must be set together. "
            "Set both paths or unset both, then restart the bot."
        )
    if not cert_path:
        return None
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    try:
        context.load_cert_chain(certfile=cert_path, keyfile=key_path)
    except (OSError, ssl.SSLError) as exc:
        raise ValueError(
            "StackChan TLS certificate or key could not be loaded. Check both PEM paths "
            "and the key permissions, then restart the bot."
        ) from exc
    return context


def generate_local_ca(output_dir: Path, host: str) -> tuple[Path, Path, Path]:
    """Create a private local CA and host certificate with a matching SAN."""
    openssl = shutil.which("openssl")
    if not openssl:
        raise RuntimeError(
            "OpenSSL is required to generate local TLS files. Install OpenSSL and retry."
        )
    if not host or any(char in host for char in "\r\n,/"):
        raise ValueError("Host must be a LAN hostname or IP address. Provide one and retry.")
    try:
        san = f"IP:{ipaddress.ip_address(host)}"
    except ValueError:
        san = f"DNS:{host}"

    output_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    if output_dir.is_symlink() or not output_dir.is_dir():
        raise ValueError(
            "Output path must be a private directory. Choose a normal directory and retry."
        )
    output_dir.chmod(0o700)
    ca_key = output_dir / "ca-key.pem"
    ca_cert = output_dir / "ca.pem"
    server_key = output_dir / "server-key.pem"
    server_csr = output_dir / "server.csr"
    server_cert = output_dir / "server.pem"
    extension_file = output_dir / "server.ext"
    extension_file.write_text(
        "basicConstraints=CA:FALSE\n"
        "keyUsage=digitalSignature,keyEncipherment\n"
        "extendedKeyUsage=serverAuth\n"
        f"subjectAltName={san}\n"
    )
    extension_file.chmod(0o600)
    commands = [
        [openssl, "genrsa", "-out", str(ca_key), "3072"],
        [
            openssl,
            "req",
            "-x509",
            "-new",
            "-nodes",
            "-key",
            str(ca_key),
            "-sha256",
            "-days",
            "3650",
            "-subj",
            "/CN=MaiPai StackChan Local CA",
            "-out",
            str(ca_cert),
        ],
        [openssl, "genrsa", "-out", str(server_key), "2048"],
        [
            openssl,
            "req",
            "-new",
            "-key",
            str(server_key),
            "-subj",
            f"/CN={host}",
            "-out",
            str(server_csr),
        ],
        [
            openssl,
            "x509",
            "-req",
            "-in",
            str(server_csr),
            "-CA",
            str(ca_cert),
            "-CAkey",
            str(ca_key),
            "-CAcreateserial",
            "-out",
            str(server_cert),
            "-days",
            "825",
            "-sha256",
            "-extfile",
            str(extension_file),
        ],
    ]
    try:
        for command in commands:
            subprocess.run(command, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        for path in output_dir.iterdir():
            if path.is_file():
                path.unlink()
        raise RuntimeError(
            "OpenSSL could not generate the local CA and server certificate. Check the host "
            "and output directory, then retry."
        ) from exc
    for path in output_dir.iterdir():
        if path.is_file():
            path.chmod(0o600)
    return ca_cert, server_cert, server_key
