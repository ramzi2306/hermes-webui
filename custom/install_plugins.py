"""
Run at container startup to install custom plugins into Hermes home.
Called from api/startup.py or server.py.
"""
import shutil
import os
from pathlib import Path


def _hermes_base(hermes_home: Path) -> Path:
    """Resolve the BASE .hermes dir (not a profile subdir)."""
    if hermes_home.parent.name == "profiles":
        return hermes_home.parent.parent
    return hermes_home


def install_custom_plugins():
    """Copy custom plugins + skills into Hermes home so the agent can load them."""
    hermes_home = Path(os.getenv("HERMES_HOME", Path.home() / ".hermes"))
    base = _hermes_base(hermes_home)
    plugins_dir = base / "plugins"
    skills_dir = base / "skills"

    custom_root = Path(__file__).parent

    # 0. Bundle the WHOLE custom package into the shared Hermes home so the
    #    AGENT container (separate from webui) can `import custom.email`.
    #    base is on the shared hermes-home volume → agent sees the same files.
    try:
        pkg_dest = base / "custom"
        if pkg_dest.exists():
            shutil.rmtree(pkg_dest)
        shutil.copytree(
            str(custom_root), str(pkg_dest),
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".gitignore"),
        )
        print(f"[custom] Bundled custom package -> {pkg_dest} (importable by agent)")
    except Exception as e:
        print(f"[custom] Warning: could not bundle custom package: {e}")

    # 1. Install plugins (tool handlers + schemas)
    for plugin_dir in custom_root.glob("*/plugin"):
        if not plugin_dir.is_dir():
            continue
        feature_name = plugin_dir.parent.name
        dest = plugins_dir / feature_name
        try:
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(str(plugin_dir), str(dest))
            print(f"[custom] Installed plugin: {feature_name} -> {dest}")
        except Exception as e:
            print(f"[custom] Warning: could not install plugin {feature_name}: {e}")

    # 2. Install skills (SKILL.md telling the agent HOW to use the tools)
    for skill_dir in custom_root.glob("*/skill"):
        if not skill_dir.is_dir() or not (skill_dir / "SKILL.md").exists():
            continue
        feature_name = skill_dir.parent.name
        dest = skills_dir / f"{feature_name}-manager"
        try:
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(skill_dir / "SKILL.md"), str(dest / "SKILL.md"))
            print(f"[custom] Installed skill: {feature_name} -> {dest}")
        except Exception as e:
            print(f"[custom] Warning: could not install skill {feature_name}: {e}")

    _ensure_plugin_enabled("email", base)


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
