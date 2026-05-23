import re

from harbor.composition.ids import UuidIdFactory


def test_new_deployment_id_has_expected_shape() -> None:
    factory = UuidIdFactory()
    ident = factory.new_deployment_id()
    assert isinstance(ident, str)
    assert re.fullmatch(r"dep_[0-9a-f]{12}", ident) is not None


def test_new_deployment_id_is_unique_per_call() -> None:
    factory = UuidIdFactory()
    ids = {factory.new_deployment_id() for _ in range(50)}
    assert len(ids) == 50
