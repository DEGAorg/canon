"""Persistent public Cardano configuration; signing secrets stay in TypeScript."""

from dataclasses import dataclass
import json
import os
import tempfile
from pathlib import Path

from toad.extensions.dega_panel import auth_store
from toad.extensions.dega_panel.registry_client import RegistryError


@dataclass(frozen=True)
class CardanoConfig:
    network: str
    wallet_path: Path
    deployment: Path
    registration_backend: str | None = None


def config_path() -> Path:
    default = auth_store.CANON_DIR / "cardano/config.json"
    return Path(os.environ.get("CANON_CARDANO_CONFIG", default))


def default_deployment(network: str) -> Path:
    """Locate the production manifest independently of the working directory."""
    if network == "Preview":
        return auth_store.CANON_DIR / "cardano/deployment.json"
    packaged = Path(__file__).with_name("cardano_client") / "deployments/mainnet.json"
    source = Path(__file__).resolve().parents[4] / "cardano/deployments/mainnet.json"
    return packaged if packaged.is_file() else source


def load_cardano_config() -> CardanoConfig:
    """Read public settings and explicit development overrides without creating a wallet."""
    path = config_path().expanduser()
    try:
        raw = json.loads(path.read_text()) if path.exists() else {}
        if not isinstance(raw, dict):
            raise ValueError("configuration must be an object")
        network = os.environ.get("CANON_CARDANO_NETWORK") or raw.get("network", "Mainnet")
        if network not in ("Mainnet", "Preview"):
            raise ValueError("unsupported network")
        base = auth_store.CANON_DIR / "cardano"
        wallet = os.environ.get("CANON_CARDANO_WALLET") or raw.get(
            "walletPath", str(base / "wallets" / network.lower()))
        deployment = os.environ.get("CANON_CARDANO_DEPLOYMENT") or raw.get(
            "deployment", str(default_deployment(network)))
        wallet_path, deployment_path = Path(wallet).expanduser(), Path(deployment).expanduser()
        if not wallet_path.is_absolute() or not deployment_path.is_absolute():
            raise ValueError("paths must be absolute")
        selected = raw.get("registrationChain")
        if selected not in (None, "ethereum", "cardano"):
            raise ValueError("unsupported registration chain")
        backend = "chain" if selected == "ethereum" else selected
        return CardanoConfig(network, wallet_path, deployment_path, backend)
    except (OSError, ValueError, TypeError) as exc:
        raise RegistryError(
            f"Invalid Cardano configuration at {path}; check network and paths"
        ) from exc


def persist_default_config(config: CardanoConfig) -> None:
    """Create public startup settings once without replacing existing user configuration."""
    path = config_path().expanduser()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    payload = {"network": config.network, "walletPath": str(config.wallet_path),
               "deployment": str(config.deployment)}
    if config.registration_backend is not None:
        payload["registrationChain"] = (
            "ethereum" if config.registration_backend == "chain" else "cardano")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as output:
            temporary = Path(output.name)
            json.dump(payload, output, indent=2)
        try:
            os.link(temporary, path)
        except FileExistsError:
            return
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def save_registration_backend(backend: str) -> None:
    """Persist the selected registration chain without changing wallet or deployment settings."""
    if backend not in ("chain", "cardano"):
        raise RegistryError("Unsupported registration chain")
    settings = load_cardano_config()
    persist_default_config(settings)
    path = config_path().expanduser()
    temporary: Path | None = None
    try:
        payload = json.loads(path.read_text())
        payload["registrationChain"] = "ethereum" if backend == "chain" else "cardano"
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as output:
            temporary = Path(output.name)
            json.dump(payload, output, indent=2)
        temporary.replace(path)
    except (OSError, ValueError, TypeError) as exc:
        raise RegistryError("Could not save the selected registration chain") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
