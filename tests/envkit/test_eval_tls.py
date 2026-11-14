"""Modal's TLS fallback is isolated to Harbor and respects host configuration."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from envkit.evalrun import harbor_environment, run_command


class ModalCertificateTests(unittest.TestCase):
    @patch.dict(os.environ, {}, clear=True)
    def test_local_backend_does_not_inspect_or_change_trust(self):
        with patch("envkit.evalrun.ssl.create_default_context") as context:
            self.assertIsNone(harbor_environment("docker"))
            context.assert_not_called()

    @patch.dict(os.environ, {}, clear=True)
    def test_existing_system_trust_is_preserved(self):
        trusted = SimpleNamespace(get_ca_certs=lambda: [{"subject": "trusted"}])
        with patch("envkit.evalrun.ssl.create_default_context", return_value=trusted):
            self.assertIsNone(harbor_environment("modal"))
        self.assertNotIn("SSL_CERT_FILE", os.environ)

    @patch.dict(os.environ, {}, clear=True)
    def test_zero_system_cas_uses_bundle_only_in_child(self):
        empty = SimpleNamespace(get_ca_certs=lambda: [])
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory) / "cacert.pem"
            bundle.write_text("test fixture")
            with patch("envkit.evalrun.ssl.create_default_context", return_value=empty), \
                 patch("certifi.where", return_value=str(bundle)):
                child_env = harbor_environment("modal")
            self.assertEqual(child_env["SSL_CERT_FILE"], str(bundle))
            self.assertNotIn("SSL_CERT_FILE", os.environ)
            log = Path(directory) / "child.log"
            result = run_command([sys.executable, "-c", "import os; print(os.environ['SSL_CERT_FILE'])"],
                                 log, env=child_env)
            self.assertEqual(result["exit_code"], 0)
            self.assertEqual(log.read_text().strip(), str(bundle))

    def test_explicit_bundle_and_directory_take_precedence(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory) / "custom.pem"
            bundle.write_text("test fixture")
            with patch.dict(os.environ, {"SSL_CERT_FILE": str(bundle), "SSL_CERT_DIR": directory}, clear=True), \
                 patch("envkit.evalrun.ssl.create_default_context") as context:
                self.assertIsNone(harbor_environment("modal"))
                context.assert_not_called()

    def test_invalid_explicit_path_fails_actionably(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = str(Path(directory) / "missing.pem")
            with patch.dict(os.environ, {"SSL_CERT_FILE": missing}, clear=True):
                with self.assertRaisesRegex(RuntimeError, "SSL_CERT_FILE.*Fix or unset"):
                    harbor_environment("modal")
            with patch.dict(os.environ, {"SSL_CERT_DIR": missing}, clear=True):
                with self.assertRaisesRegex(RuntimeError, "SSL_CERT_DIR.*Fix or unset"):
                    harbor_environment("modal")


if __name__ == "__main__":
    unittest.main()
