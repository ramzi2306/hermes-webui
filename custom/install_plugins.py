"""
Run at container startup to install custom plugins into Hermes home.
Called from api/startup.py or server.py.
"""
import shutil
import os
from pathlib import Path


def install_custom_plugins():
    """Copy custom plugins to ~/.hermes/plugins/ so Hermes can load them."""
    hermes_home = Path(os.getenv("HERMES_HOME", Path.home() / ".hermes"))
    plugins_dir = hermes_home / "plugins"

    custom_root = Path(__file__).parent

    for plugin_dir in (custom_root).glob("*/plugin"):
        if not plugin_dir.is_dir():
            continue
        feature_name = plugin_dir.parent.name
        dest = plugins_dir / feature_name
        try:
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(str(plugin_dir), str(dest))
            print(f"[custom] Installed plugin: {feature_name} → {dest}")
        except Exception as e:
            print(f"[custom] Warning: could not install plugin {feature_name}: {e}")

    # Also enable plugin in config if not already enabled
    _ensure_plugin_enabled("email", hermes_home)


def _ensure_plugin_enabled(plugin_name: str, hermes_home: Path):
    """Add plugin to plugins.enabled in config.yaml if missing."""
    try:
        import yaml
        config_path = hermes_home / "config.yaml"
        if not config_path.exists():
            return
        with open(config_path, "r") as f:
            config = yaml.safe_load(f) or {}
        plugins = config.setdefault("plugins", {})
        enabled = plugins.setdefault("enabled", [])
        if plugin_name not in enabled:
            enabled.append(plugin_name)
            with open(config_path, "w") as f:
                yaml.dump(config, f, default_flow_style=False)
            print(f"[custom] Enabled plugin '{plugin_name}' in config.yaml")
    except Exception as e:
        print(f"[custom] Could not update config.yaml for plugin '{plugin_name}': {e}")


if __name__ == "__main__":
    install_custom_plugins()
