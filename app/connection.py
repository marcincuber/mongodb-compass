"""Validate runtime connection variables and the DocumentDB TLS policy."""

import json
from pathlib import Path
import re
import ssl
import time
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit
import uuid


class ConfigurationError(ValueError):
    """An error safe to report without including connection secrets."""


def secret(env, name):
    value, filename = env.get(name, ""), env.get(name + "_FILE", "")
    if value and filename:
        raise ConfigurationError(f"Set only one of {name} and {name}_FILE")
    if filename:
        try:
            value = Path(filename).read_text().rstrip("\r\n")
        except (OSError, UnicodeError):
            raise ConfigurationError(f"Cannot read {name}_FILE") from None
    return value


OPTION_ENV = {
    "MONGODB_AUTH_SOURCE": "authSource",
    "MONGODB_AUTH_MECHANISM": "authMechanism",
    "MONGODB_AUTH_MECHANISM_PROPERTIES": "authMechanismProperties",
    "MONGODB_REPLICA_SET": "replicaSet",
    "MONGODB_READ_PREFERENCE": "readPreference",
    "MONGODB_RETRY_WRITES": "retryWrites",
    "MONGODB_DIRECT_CONNECTION": "directConnection",
    "MONGODB_TLS": "tls",
    "MONGODB_TLS_INSECURE": "tlsInsecure",
    "MONGODB_TLS_CA_FILE": "tlsCAFile",
    "MONGODB_TLS_CERTIFICATE_KEY_FILE": "tlsCertificateKeyFile",
    "MONGODB_TLS_CERTIFICATE_KEY_FILE_PASSWORD": "tlsCertificateKeyFilePassword",
    "MONGODB_TLS_ALLOW_INVALID_CERTIFICATES": "tlsAllowInvalidCertificates",
    "MONGODB_TLS_ALLOW_INVALID_HOSTNAMES": "tlsAllowInvalidHostnames",
    "MONGODB_SERVER_SELECTION_TIMEOUT_MS": "serverSelectionTimeoutMS",
    "MONGODB_CONNECT_TIMEOUT_MS": "connectTimeoutMS",
}
BOOL_OPTIONS = {
    "tls", "ssl", "retrywrites", "retryreads", "directconnection",
    "tlsallowinvalidcertificates", "tlsallowinvalidhostnames", "tlsinsecure",
    "loadbalanced",
}


def validate_documentdb_tls_option(key, value):
    key = key.lower()
    if key in {"tls", "ssl"} and value.lower() != "true":
        raise ConfigurationError("DocumentDB requires TLS; tls/ssl must be true")
    if key in {"tlsinsecure", "tlsallowinvalidcertificates", "tlsallowinvalidhostnames"} and value.lower() != "false":
        raise ConfigurationError("DocumentDB requires certificate and hostname verification; insecure TLS options must be false")


def validate_documentdb_ca(filename):
    if not filename:
        raise ConfigurationError("DocumentDB requires a TLS CA file")
    try:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        # OpenSSL performs the actual read and PEM/X.509 parsing under the container UID.
        context.load_verify_locations(cafile=filename)
        now = time.time()
        if not any(ssl.cert_time_to_seconds(cert["notBefore"]) <= now < ssl.cert_time_to_seconds(cert["notAfter"])
                   for cert in context.get_ca_certs()):
            raise ValueError("No currently valid CA certificates")
    except (OSError, ValueError, KeyError):
        raise ConfigurationError("DocumentDB TLS CA file must be readable PEM containing a currently valid CA certificate") from None


def unique_option_keys(pairs):
    result = {}
    seen = set()
    for key, value in pairs:
        if key.lower() in seen:
            raise ConfigurationError("MONGODB_OPTIONS must not contain duplicate option keys; use arrays for repeated values")
        seen.add(key.lower())
        result[key] = value
    return result


def build_connection(env):
    preset = env.get("CONNECTION_TYPE", "mongodb").lower()
    if preset not in {"mongodb", "documentdb"}:
        raise ConfigurationError("CONNECTION_TYPE must be mongodb or documentdb")
    uri = secret(env, "MONGODB_URI")
    host = env.get("MONGODB_HOST", "")
    if not uri and not host:
        configured = any(value for key, value in env.items()
                         if key.startswith(("MONGODB_", "SSH_")))
        if configured or preset == "documentdb":
            raise ConfigurationError("Set MONGODB_URI or MONGODB_HOST for a connection")
        return None
    if not uri:
        uri = "mongodb://localhost/"
    try:
        parsed = urlsplit(uri)
    except ValueError:
        raise ConfigurationError("Invalid MONGODB_URI") from None
    scheme = env.get("MONGODB_SCHEME") or parsed.scheme
    if scheme not in {"mongodb", "mongodb+srv"} or not parsed.netloc or parsed.fragment:
        raise ConfigurationError("Use a valid mongodb:// or mongodb+srv:// URI")
    hosts = host or parsed.netloc.rsplit("@", 1)[-1]
    if re.search(r"[\s/@?#]", hosts):
        raise ConfigurationError("MONGODB_HOST must contain only hosts and optional ports")
    port = env.get("MONGODB_PORT", "")
    if port:
        if scheme == "mongodb+srv" or "," in hosts:
            raise ConfigurationError("MONGODB_PORT requires one non-SRV host")
        if not port.isascii() or not port.isdigit() or not 1 <= int(port) <= 65535:
            raise ConfigurationError("MONGODB_PORT must be between 1 and 65535")
        # Allow a bracketed IPv6 address, with or without an existing port.
        if hosts.startswith("["):
            if "]" not in hosts:
                raise ConfigurationError("Use brackets around IPv6 addresses")
            hosts = hosts[:hosts.index("]") + 1]
        else:
            if hosts.count(":") > 1:
                raise ConfigurationError("Use brackets around IPv6 addresses")
            hosts = hosts.split(":", 1)[0]
        hosts += ":" + port
    if scheme == "mongodb+srv" and (":" in hosts or "," in hosts):
        raise ConfigurationError("SRV connections require one DNS hostname without a port")

    # Keep duplicate URI options, e.g. readPreferenceTags, and compare keys case-insensitively.
    options = parse_qsl(parsed.query, keep_blank_values=True)
    if preset == "documentdb":
        for key, value in options:
            validate_documentdb_tls_option(key, value)

    def get_option(key):
        return next((v for k, v in reversed(options) if k.lower() == key.lower()), "")

    def set_option(key, values):
        options[:] = [(k, v) for k, v in options if k.lower() != key.lower()]
        for value in values if isinstance(values, list) else [values]:
            if not isinstance(value, (str, bool, int, float)):
                raise ConfigurationError("MONGODB_OPTIONS values must be scalars or lists of scalars")
            value = str(value).lower() if isinstance(value, bool) else str(value)
            if key.lower() in BOOL_OPTIONS:
                if value.lower() not in {"true", "false"}:
                    raise ConfigurationError(f"{key} must be true or false")
                value = value.lower()
            if preset == "documentdb":
                validate_documentdb_tls_option(key, value)
            # ssl and tls are aliases: an explicit override replaces either spelling.
            if key.lower() in {"tls", "ssl"}:
                options[:] = [(k, v) for k, v in options if k.lower() not in {"tls", "ssl"}]
            options.append((key, value))

    if preset == "documentdb":
        defaults = {
            "tls": "true", "tlsCAFile": "/opt/certs/global-bundle.pem",
            "replicaSet": "rs0", "readPreference": "secondaryPreferred", "retryWrites": "false",
        }
        for key, value in defaults.items():
            if not get_option(key) and not (key == "tls" and get_option("ssl")):
                set_option(key, value)
    try:
        extra = json.loads(env.get("MONGODB_OPTIONS") or "{}", object_pairs_hook=unique_option_keys)
    except (json.JSONDecodeError, TypeError):
        raise ConfigurationError("MONGODB_OPTIONS must be a JSON object") from None
    if not isinstance(extra, dict):
        raise ConfigurationError("MONGODB_OPTIONS must be a JSON object")
    for key, value in extra.items():
        if not key:
            raise ConfigurationError("MONGODB_OPTIONS keys must be nonempty")
        set_option(key, value)
    for variable, option in OPTION_ENV.items():
        value = secret(env, variable) if variable.endswith("_PASSWORD") else env.get(variable, "")
        if value:
            set_option(option, value)
    if preset == "documentdb" and not get_option("authSource"):
        mechanism = get_option("authMechanism")
        set_option("authSource", "$external" if mechanism in {"MONGODB-AWS", "MONGODB-X509"} else "admin")
    if get_option("directConnection").lower() == "true":
        # Direct connections (e.g. a tunnel) cannot discover the replica set.
        if preset == "documentdb" and not env.get("MONGODB_REPLICA_SET") and not any(
            k.lower() == "replicaset" for k in extra
        ) and not any(k.lower() == "replicaset" for k, _ in parse_qsl(parsed.query)):
            options[:] = [(k, v) for k, v in options if k.lower() != "replicaset"]
    if preset == "documentdb":
        # Check the effective policy too: e.g. an empty JSON array may remove a required option.
        if not any(k.lower() in {"tls", "ssl"} for k, _ in options):
            raise ConfigurationError("DocumentDB requires TLS; tls/ssl cannot be removed")
        for key, value in options:
            validate_documentdb_tls_option(key, value)
        validate_documentdb_ca(get_option("tlsCAFile"))
        # Emit one canonical, verified configuration. tlsInsecure is mutually exclusive
        # with the driver's granular verification flags, even when set to false.
        options[:] = [(k, v) for k, v in options if k.lower() != "tlsinsecure"]
        set_option("tls", "true")
        set_option("tlsAllowInvalidCertificates", "false")
        set_option("tlsAllowInvalidHostnames", "false")
    for key, value in options:
        if key.lower() in BOOL_OPTIONS and value.lower() not in {"true", "false"}:
            raise ConfigurationError(f"{key} must be true or false")
        if key.lower() in {"tlscafile", "tlscertificatekeyfile"} and not Path(value).is_file():
            raise ConfigurationError(f"Mount a readable file for {key}")
    username = secret(env, "MONGODB_USERNAME") or unquote(parsed.username or "")
    password = secret(env, "MONGODB_PASSWORD") or unquote(parsed.password or "")
    if password and not username:
        raise ConfigurationError("MONGODB_PASSWORD requires MONGODB_USERNAME")
    auth = ""
    if username:
        auth = quote(username, safe="")
        if password:
            auth += ":" + quote(password, safe="")
        auth += "@"
    database = env.get("MONGODB_DATABASE")
    dbpath = "/" + quote(database, safe="") if database else parsed.path or "/"
    connection_string = urlunsplit((scheme, auth + hosts, dbpath, urlencode(options), ""))
    result = {
        "id": str(uuid.uuid5(uuid.NAMESPACE_URL, "compass-container-environment")),
        "favorite": {"name": env.get("COMPASS_CONNECTION_NAME") or preset},
        "savedConnectionType": "favorite",
        "connectionOptions": {"connectionString": connection_string},
    }
    return result
