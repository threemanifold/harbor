from harbor.domain.catalog import ModelRef, WeightsDtype
from harbor.infrastructure.catalog.static import (
    QWEN2_5_3B_INSTRUCT,
    QWEN2_5_7B_INSTRUCT,
    QWEN_DEFAULT_ENTRIES,
    StaticModelCatalog,
)


async def test_qwen_default_lookup_returns_three_b_entry() -> None:
    catalog = StaticModelCatalog.qwen_default()
    entry = await catalog.get(ModelRef(identifier="Qwen/Qwen2.5-3B-Instruct"))
    assert entry is QWEN2_5_3B_INSTRUCT
    assert entry.parameters_billion == QWEN2_5_3B_INSTRUCT.parameters_billion
    assert entry.native_dtype is WeightsDtype.BF16


async def test_qwen_default_lookup_returns_seven_b_entry() -> None:
    catalog = StaticModelCatalog.qwen_default()
    entry = await catalog.get(ModelRef(identifier="Qwen/Qwen2.5-7B-Instruct"))
    assert entry is QWEN2_5_7B_INSTRUCT
    assert entry.parameters_billion > QWEN2_5_3B_INSTRUCT.parameters_billion


async def test_unknown_ref_returns_none() -> None:
    catalog = StaticModelCatalog.qwen_default()
    assert await catalog.get(ModelRef(identifier="acme/unknown")) is None


async def test_custom_entries_are_honoured() -> None:
    only_seven = StaticModelCatalog((QWEN2_5_7B_INSTRUCT,))
    assert await only_seven.get(QWEN2_5_3B_INSTRUCT.ref) is None
    assert await only_seven.get(QWEN2_5_7B_INSTRUCT.ref) is QWEN2_5_7B_INSTRUCT


def test_qwen_default_entries_exposes_both_qwen_models() -> None:
    refs = {entry.ref.identifier for entry in QWEN_DEFAULT_ENTRIES}
    assert refs == {"Qwen/Qwen2.5-3B-Instruct", "Qwen/Qwen2.5-7B-Instruct"}
