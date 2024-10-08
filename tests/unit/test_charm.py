# Copyright 2024 Canonical
# See LICENSE file for licensing details.
#
# Learn more about testing at: https://juju.is/docs/sdk/testing

from typing import Type

import ops
import ops.testing
import pytest

import charm
from charm import CalibreWebCharm

# let's look at scenario for further unit tests


@pytest.fixture
def harness():
    harness = ops.testing.Harness(CalibreWebCharm)
    harness.begin()
    yield harness
    harness.cleanup()


## doesn't work anymore since _on_pebble_ready calls container.exec
## and _push_library_to_container
## will need to rewrite
#def test_pebble_ready(harness: ops.testing.Harness[CalibreWebCharm]):
#    # expected == actual
#    harness.container_pebble_ready(charm.CONTAINER_NAME)
#    updated_plan = harness.get_container_pebble_plan(charm.CONTAINER_NAME).to_dict()
#    expected_plan = {'services': CalibreWebCharm.get_pebble_layer()['services']}
#    assert expected_plan == updated_plan
#    # running and active
#    service = harness.model.unit.get_container(charm.CONTAINER_NAME).get_service(
#        charm.SERVICE_NAME
#    )
#    harness.evaluate_status()
#    assert service.is_running()
#    assert harness.model.unit.status == ops.ActiveStatus()


@pytest.mark.parametrize(
    "val,status_type",
    [
        ("bad-value", ops.BlockedStatus),
        *((val, ops.ActiveStatus) for val in charm.LIBRARY_WRITE_BEHAVIOURS),
    ]
)
def test_config_changed(
    harness: ops.testing.Harness[CalibreWebCharm], val: str, status_type: Type[ops.StatusBase]
):
    harness.set_can_connect(charm.CONTAINER_NAME, True)
    harness.update_config({charm.LIBRARY_WRITE_CONFIG: val})
    harness.evaluate_status()
    assert isinstance(harness.model.unit.status, status_type)
