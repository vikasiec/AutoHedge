from autohedge.env_loader import load_env

load_env()

__all__ = ["AutoHedge"]


def __getattr__(name: str):
    # Lazy import: autohedge.main pulls in `swarms` (and its heavy deps),
    # which submodules like autohedge.portfolio/risk_engine/schemas don't
    # need. Deferring this means `import autohedge.portfolio` etc. stays
    # lightweight and testable without the swarms/LLM stack installed.
    if name == "AutoHedge":
        from autohedge.main import AutoHedge

        return AutoHedge
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
