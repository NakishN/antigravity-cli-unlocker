"""
CA Certificate Manager for MITM TLS Proxy.
Generates a local CA certificate and per-domain leaf certificates for TLS interception.
"""

import os
import datetime
import ipaddress
import platform

from cryptography import x509
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend

CA_KEY_BITS = 2048
LEAF_KEY_BITS = 2048
CA_CERT_VALIDITY_DAYS = 3650   # 10 years
LEAF_CERT_VALIDITY_DAYS = 365  # 1 year


def get_ca_dir():
    """Returns the directory where CA key/cert are stored."""
    if platform.system() == "Windows":
        base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
    else:
        base = os.path.join(os.path.expanduser("~"), ".local", "share")
    ca_dir = os.path.join(base, "antigravity-unlocker", "ca")
    os.makedirs(ca_dir, exist_ok=True)
    return ca_dir


def _generate_ca_keypair():
    """Generates CA private key and self-signed certificate."""
    key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=CA_KEY_BITS,
        backend=default_backend(),
    )
    now = datetime.datetime.now(datetime.timezone.utc)
    subject = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "Antigravity Unlocker Local CA"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Antigravity Unlocker"),
    ])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=CA_CERT_VALIDITY_DAYS))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, key_cert_sign=True, crl_sign=True,
                content_commitment=False, key_encipherment=False,
                data_encipherment=False, key_agreement=False,
                encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(key.public_key()),
            critical=False,
        )
        .sign(key, hashes.SHA256(), default_backend())
    )
    return key, cert


def get_or_create_ca():
    """
    Loads existing CA key/cert or creates a new one.
    Returns (ca_key, ca_cert, ca_cert_pem_path).
    """
    ca_dir = get_ca_dir()
    key_path = os.path.join(ca_dir, "ca.key")
    cert_path = os.path.join(ca_dir, "ca.crt")

    if os.path.exists(key_path) and os.path.exists(cert_path):
        with open(key_path, "rb") as f:
            ca_key = serialization.load_pem_private_key(f.read(), password=None, backend=default_backend())
        with open(cert_path, "rb") as f:
            ca_cert = x509.load_pem_x509_certificate(f.read(), default_backend())
        return ca_key, ca_cert, cert_path

    ca_key, ca_cert = _generate_ca_keypair()

    with open(key_path, "wb") as f:
        f.write(ca_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ))
    os.chmod(key_path, 0o600)

    with open(cert_path, "wb") as f:
        f.write(ca_cert.public_bytes(serialization.Encoding.PEM))

    return ca_key, ca_cert, cert_path


def generate_leaf_cert(hostname, ca_key, ca_cert):
    """
    Generates a leaf TLS certificate for the given hostname, signed by the local CA.
    Returns (leaf_key_pem_bytes, leaf_cert_pem_bytes).
    """
    leaf_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=LEAF_KEY_BITS,
        backend=default_backend(),
    )
    now = datetime.datetime.now(datetime.timezone.utc)
    subject = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, hostname),
    ])

    san_list = [x509.DNSName(hostname)]
    # Add wildcard SAN so *.googleapis.com cert covers all subdomains
    parts = hostname.split(".")
    if len(parts) >= 2:
        wildcard = "*." + ".".join(parts[-2:])
        if wildcard != hostname:
            san_list.append(x509.DNSName(wildcard))

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_cert.subject)
        .public_key(leaf_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=LEAF_CERT_VALIDITY_DAYS))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.SubjectAlternativeName(san_list), critical=False)
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256(), default_backend())
    )

    key_pem = leaf_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    return key_pem, cert_pem


def install_ca_system(ca_cert_path):
    """
    Installs the local CA certificate into the system trust store.
    Supports Linux (update-ca-certificates / update-ca-trust) and macOS.
    Returns (success, message).
    """
    import subprocess
    import shutil

    system = platform.system()
    if system == "Linux":
        # Try Debian/Ubuntu path
        if shutil.which("update-ca-certificates"):
            dest = "/usr/local/share/ca-certificates/antigravity-unlocker.crt"
            try:
                subprocess.run(["sudo", "cp", ca_cert_path, dest], check=True, capture_output=True)
                subprocess.run(["sudo", "update-ca-certificates"], check=True, capture_output=True)
                return True, f"Installed CA to {dest} and ran update-ca-certificates"
            except subprocess.CalledProcessError as e:
                return False, f"update-ca-certificates failed: {e.stderr.decode(errors='replace')[:200]}"

        # Try Fedora/RHEL path
        if shutil.which("update-ca-trust"):
            dest = "/etc/pki/ca-trust/source/anchors/antigravity-unlocker.crt"
            try:
                subprocess.run(["sudo", "cp", ca_cert_path, dest], check=True, capture_output=True)
                subprocess.run(["sudo", "update-ca-trust"], check=True, capture_output=True)
                return True, f"Installed CA to {dest} and ran update-ca-trust"
            except subprocess.CalledProcessError as e:
                return False, f"update-ca-trust failed: {e.stderr.decode(errors='replace')[:200]}"

    elif system == "Darwin":
        try:
            subprocess.run(
                ["sudo", "security", "add-trusted-cert", "-d", "-r", "trustRoot",
                 "-k", "/Library/Keychains/System.keychain", ca_cert_path],
                check=True, capture_output=True,
            )
            return True, "Installed CA into macOS System Keychain"
        except subprocess.CalledProcessError as e:
            return False, f"macOS security add-trusted-cert failed: {e.stderr.decode(errors='replace')[:200]}"

    return False, f"Unsupported platform: {system}"
