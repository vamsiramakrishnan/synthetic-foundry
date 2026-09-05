from types import SimpleNamespace

from worldloom.render import pptx


def _ir(**metadata: str):  # type: ignore[no-untyped-def]
    return SimpleNamespace(metadata=metadata)


def test_pptx_ecology_density_maps_to_compiler_profiles() -> None:
    assert pptx._density_profile(_ir(artifact_density="airy")) == "sparse"  # type: ignore[attr-defined]
    assert pptx._density_profile(_ir(artifact_density="balanced")) == "balanced"  # type: ignore[attr-defined]
    assert pptx._density_profile(_ir(artifact_density="compact")) == "dense"  # type: ignore[attr-defined]


def test_pptx_legacy_ir_keeps_balanced_density() -> None:
    assert pptx._density_profile(_ir()) == "balanced"  # type: ignore[attr-defined]
