import json
import os
from pathlib import Path
import ssl
import subprocess
import sys
import tempfile
import unittest
from urllib.parse import parse_qsl, unquote, urlsplit
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from connection import ConfigurationError, build_connection, secret


class ConnectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(directory.cleanup)
        cls.ca_file = str(Path(directory.name) / "ca.pem")
        cls.ca_key = str(Path(directory.name) / "ca.key")
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                        "-days", "2", "-subj", "/CN=Compass Test CA",
                        "-addext", "basicConstraints=critical,CA:TRUE",
                        "-keyout", cls.ca_key, "-out", cls.ca_file], check=True, capture_output=True)

    def connection(self, **env):
        return build_connection({"MONGODB_HOST": "db.example", **env})

    def uri(self, **env):
        return self.connection(**env)["connectionOptions"]["connectionString"]

    def test_empty_environment_opens_unconfigured_ui(self):
        self.assertIsNone(build_connection({}))

    def test_partial_configuration_is_rejected(self):
        for env in ({"MONGODB_PASSWORD": "secret"}, {"CONNECTION_TYPE": "documentdb"}):
            with self.subTest(env=env), self.assertRaises(ConfigurationError):
                build_connection(env)

    def test_credential_and_database_encoding(self):
        parsed = urlsplit(self.uri(MONGODB_USERNAME="u@:/", MONGODB_PASSWORD="a?#@:/%$! ",
                                   MONGODB_DATABASE="db/name ?"))
        self.assertEqual(unquote(parsed.username), "u@:/")
        self.assertEqual(unquote(parsed.password), "a?#@:/%$! ")
        self.assertEqual(unquote(parsed.path), "/db/name ?")

    def test_srv_uri_preserved(self):
        result = build_connection({"MONGODB_URI": "mongodb+srv://u:p@cluster.example/db?retryWrites=true"})
        self.assertEqual(result["connectionOptions"]["connectionString"],
                         "mongodb+srv://u:p@cluster.example/db?retryWrites=true")

    def test_individual_variables_override_uri(self):
        parsed = urlsplit(self.uri(MONGODB_URI="mongodb://old:old@old.example:1234/old?TLS=false",
                                   MONGODB_USERNAME="new", MONGODB_PASSWORD="new",
                                   MONGODB_PORT="27018", MONGODB_DATABASE="new", MONGODB_TLS="true"))
        self.assertEqual(parsed.netloc, "new:new@db.example:27018")
        self.assertEqual(parsed.path, "/new")
        self.assertEqual(dict(parse_qsl(parsed.query)), {"tls": "true"})

    def test_multiple_hosts_and_repeated_options_preserved(self):
        uri = "mongodb://one:27017,two:27018/db?readPreferenceTags=dc:a&readPreferenceTags=dc:b"
        result = build_connection({"MONGODB_URI": uri})
        parsed = urlsplit(result["connectionOptions"]["connectionString"])
        self.assertEqual(parsed.netloc, "one:27017,two:27018")
        self.assertEqual(parse_qsl(parsed.query), [("readPreferenceTags", "dc:a"), ("readPreferenceTags", "dc:b")])

    def test_options_json_and_precedence(self):
        parsed = urlsplit(self.uri(MONGODB_URI="mongodb://db/?retryWrites=true", MONGODB_RETRY_WRITES="true",
                                   MONGODB_OPTIONS='{"retryWrites":false,"readPreferenceTags":["a:1","b:2"],"maxPoolSize":5}'))
        pairs = parse_qsl(parsed.query)
        self.assertEqual([v for k, v in pairs if k == "retryWrites"], ["true"])
        self.assertEqual([v for k, v in pairs if k == "readPreferenceTags"], ["a:1", "b:2"])
        self.assertIn(("maxPoolSize", "5"), pairs)

    def test_documentdb_defaults(self):
        options = dict(parse_qsl(urlsplit(self.uri(CONNECTION_TYPE="documentdb",
                                                  MONGODB_TLS_CA_FILE=self.ca_file)).query))
        self.assertEqual(options, {"tls": "true", "tlsCAFile": self.ca_file, "replicaSet": "rs0",
                                   "readPreference": "secondaryPreferred", "retryWrites": "false", "authSource": "admin",
                                   "tlsAllowInvalidCertificates": "false", "tlsAllowInvalidHostnames": "false"})

    def test_documentdb_iam_uses_external_auth_source(self):
        options = dict(parse_qsl(urlsplit(self.uri(CONNECTION_TYPE="documentdb",
            MONGODB_AUTH_MECHANISM="MONGODB-AWS", MONGODB_TLS_CA_FILE=self.ca_file)).query))
        self.assertEqual(options["authSource"], "$external")

    def test_documentdb_non_tls_options_can_be_overridden(self):
        options = dict(parse_qsl(urlsplit(self.uri(CONNECTION_TYPE="documentdb",
            MONGODB_URI="mongodb://db/?retryWrites=true&replicaSet=custom",
            MONGODB_TLS_CA_FILE=self.ca_file)).query))
        self.assertEqual(options["tls"], "true")
        self.assertEqual(options["retryWrites"], "true")
        self.assertEqual(options["replicaSet"], "custom")

    def test_documentdb_direct_connection_omits_default_replica_set(self):
        options = dict(parse_qsl(urlsplit(self.uri(CONNECTION_TYPE="documentdb",
            MONGODB_DIRECT_CONNECTION="true", MONGODB_TLS_CA_FILE=self.ca_file)).query))
        self.assertNotIn("replicaSet", options)

    def test_documentdb_rejects_unsafe_environment_settings(self):
        for key, value in (("MONGODB_TLS", "false"), ("MONGODB_TLS_INSECURE", "true"),
                           ("MONGODB_TLS_ALLOW_INVALID_CERTIFICATES", "true"),
                           ("MONGODB_TLS_ALLOW_INVALID_HOSTNAMES", "true")):
            with self.subTest(key=key), self.assertRaises(ConfigurationError):
                self.connection(CONNECTION_TYPE="documentdb", MONGODB_TLS_CA_FILE=self.ca_file, **{key: value})

    def test_documentdb_rejects_unsafe_uri_options_even_if_overridden(self):
        for query in ("tls=false", "SSL=false", "tlsInsecure=true", "TLSAllowInvalidCertificates=true",
                      "tlsAllowInvalidHostnames=true", "tls=false&tls=true", "ssl=false&tls=true", "tls="):
            with self.subTest(query=query), self.assertRaises(ConfigurationError) as error:
                self.connection(CONNECTION_TYPE="documentdb", MONGODB_TLS_CA_FILE=self.ca_file,
                                MONGODB_URI="mongodb://user:private-password@db/?" + query, MONGODB_TLS="true")
            self.assertNotIn("private-password", str(error.exception))

    def test_documentdb_rejects_unsafe_json_options_even_if_overridden(self):
        cases = ['{"tls":false}', '{"SSL":"false"}', '{"tlsInsecure":true}',
                 '{"tlsAllowInvalidCertificates":true}', '{"tlsAllowInvalidHostnames":true}',
                 '{"tls":[false,true]}', '{"tls":[]}',
                 '{"tls":false,"tls":true}', '{"ssl":false,"SSL":true}']
        for options in cases:
            with self.subTest(options=options), self.assertRaises(ConfigurationError):
                self.connection(CONNECTION_TYPE="documentdb", MONGODB_TLS_CA_FILE=self.ca_file,
                                MONGODB_OPTIONS=options, MONGODB_TLS_ALLOW_INVALID_CERTIFICATES="false")

    def test_documentdb_required_ca_cannot_be_removed(self):
        with self.assertRaises(ConfigurationError):
            self.connection(CONNECTION_TYPE="documentdb", MONGODB_OPTIONS='{"tlsCAFile":[]}')

    def test_documentdb_canonicalizes_safe_tls_aliases(self):
        options = dict(parse_qsl(urlsplit(self.uri(CONNECTION_TYPE="documentdb",
            MONGODB_TLS_CA_FILE=self.ca_file, MONGODB_URI="mongodb://db/?SSL=true&tlsInsecure=false",
            MONGODB_TLS_INSECURE="false")).query))
        self.assertEqual(options["tls"], "true")
        self.assertEqual(options["tlsAllowInvalidCertificates"], "false")
        self.assertEqual(options["tlsAllowInvalidHostnames"], "false")
        self.assertNotIn("tlsInsecure", options)
        self.assertNotIn("SSL", options)

    def test_documentdb_rejects_missing_or_invalid_ca_files(self):
        with tempfile.TemporaryDirectory() as directory:
            bad = Path(directory) / "private-ca.pem"
            for content in ("", "not a certificate", "-----BEGIN CERTIFICATE-----\nbroken\n-----END CERTIFICATE-----\n"):
                bad.write_text(content)
                with self.subTest(content=content), self.assertRaises(ConfigurationError) as error:
                    self.connection(CONNECTION_TYPE="documentdb", MONGODB_TLS_CA_FILE=str(bad))
                self.assertNotIn(str(bad), str(error.exception))
            for filename in (str(Path(directory) / "missing.pem"), self.ca_key):
                with self.subTest(filename=filename), self.assertRaises(ConfigurationError):
                    self.connection(CONNECTION_TYPE="documentdb", MONGODB_TLS_CA_FILE=filename)

    @unittest.skipIf(os.geteuid() == 0, "root can read files without ordinary read permissions")
    def test_documentdb_rejects_unreadable_ca_file(self):
        with tempfile.NamedTemporaryFile(mode="w") as ca:
            ca.write(Path(self.ca_file).read_text())
            ca.flush()
            os.chmod(ca.name, 0)
            try:
                with self.assertRaises(ConfigurationError):
                    self.connection(CONNECTION_TYPE="documentdb", MONGODB_TLS_CA_FILE=ca.name)
            finally:
                os.chmod(ca.name, 0o600)

    def test_documentdb_rejects_expired_or_not_yet_valid_ca_bundle(self):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.load_verify_locations(cafile=self.ca_file)
        cert = context.get_ca_certs()[0]
        times = (ssl.cert_time_to_seconds(cert["notBefore"]) - 1, ssl.cert_time_to_seconds(cert["notAfter"]) + 1)
        for now in times:
            with self.subTest(now=now), patch("connection.time.time", return_value=now), self.assertRaises(ConfigurationError):
                self.connection(CONNECTION_TYPE="documentdb", MONGODB_TLS_CA_FILE=self.ca_file)


    def test_tls_ssl_alias_override(self):
        options = dict(parse_qsl(urlsplit(self.uri(MONGODB_URI="mongodb://db/?ssl=false", MONGODB_TLS="true")).query))
        self.assertEqual(options, {"tls": "true"})

    def test_invalid_inputs(self):
        cases = [
            {"MONGODB_URI": "https://db/"}, {"MONGODB_URI": "mongodb://db/#secret"},
            {"MONGODB_URI": "mongodb://[broken"}, {"CONNECTION_TYPE": "unknown"},
            {"MONGODB_PORT": "0"}, {"MONGODB_PORT": "65536"}, {"MONGODB_PORT": "x"},
            {"MONGODB_HOST": "db/path"}, {"MONGODB_HOST": "u:p@db"},
            {"MONGODB_SCHEME": "mongodb+srv", "MONGODB_PORT": "27017"},
            {"MONGODB_SCHEME": "mongodb+srv", "MONGODB_HOST": "db:27017"},
            {"MONGODB_HOST": "one,two", "MONGODB_PORT": "27017"},
            {"MONGODB_RETRY_WRITES": "yes"}, {"MONGODB_URI": "mongodb://db/?tls=maybe"},
            {"MONGODB_PASSWORD": "secret"}, {"MONGODB_OPTIONS": "[]"},
            {"MONGODB_OPTIONS": "broken"}, {"MONGODB_OPTIONS": '{"option":null}'},
            {"MONGODB_OPTIONS": '{"option":{"nested":true}}'},
            {"MONGODB_TLS_CA_FILE": "/does/not/exist"},
        ]
        for env in cases:
            with self.subTest(env=env), self.assertRaises(ConfigurationError):
                self.connection(**env)

    def test_ipv6_with_port_override(self):
        self.assertEqual(urlsplit(self.uri(MONGODB_HOST="[::1]:27017", MONGODB_PORT="27018")).netloc,
                         "[::1]:27018")

    def test_secret_files_preserve_spaces_and_strip_newlines(self):
        with tempfile.NamedTemporaryFile(mode="w") as password:
            password.write("  secret with spaces  \n")
            password.flush()
            self.assertEqual(secret({"MONGODB_PASSWORD_FILE": password.name}, "MONGODB_PASSWORD"),
                             "  secret with spaces  ")
            with self.assertRaises(ConfigurationError):
                secret({"MONGODB_PASSWORD": "secret", "MONGODB_PASSWORD_FILE": password.name}, "MONGODB_PASSWORD")

    def test_unreadable_secret_does_not_disclose_path_or_value(self):
        with self.assertRaises(ConfigurationError) as error:
            secret({"MONGODB_PASSWORD_FILE": "/secret/private-name"}, "MONGODB_PASSWORD")
        self.assertNotIn("private-name", str(error.exception))



    def test_connection_id_stable_between_credential_rotations(self):
        self.assertEqual(self.connection(MONGODB_USERNAME="a")["id"],
                         self.connection(MONGODB_USERNAME="b")["id"])



if __name__ == "__main__":
    unittest.main()
