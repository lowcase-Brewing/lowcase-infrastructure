"""Write the public browser config from `terraform output -json poc_browser_config`."""

import json
from pathlib import Path
import sys
from urllib.parse import urlparse


def main():
    config = json.load(sys.stdin)
    expected = {"apiBaseUrl", "authDomain", "clientId", "issuer", "redirectUri", "scopes"}
    if not isinstance(config, dict) or set(config) != expected:
        raise SystemExit("Expected the poc_browser_config output, not all Terraform outputs.")
    for name in ["apiBaseUrl", "authDomain", "issuer"]:
        if not isinstance(config[name], str) or urlparse(config[name]).scheme != "https":
            raise SystemExit(f"Invalid {name}; expected an HTTPS URL.")
    if not isinstance(config["clientId"], str) or not config["clientId"]:
        raise SystemExit("Missing public Cognito client ID.")
    redirect = urlparse(config["redirectUri"])
    if redirect.scheme != "https" and not (redirect.scheme == "http" and redirect.hostname == "localhost"):
        raise SystemExit("Callback must use HTTPS or localhost HTTP.")
    if not isinstance(config["scopes"], list) or not all(isinstance(scope, str) for scope in config["scopes"]):
        raise SystemExit("Invalid OAuth scopes.")
    output = Path(__file__).resolve().parents[1] / "poc/web/config.json"
    output.write_text(json.dumps(config, indent=2) + "\n")
    print(f"Wrote public POC configuration to {output}")


if __name__ == "__main__":
    main()
