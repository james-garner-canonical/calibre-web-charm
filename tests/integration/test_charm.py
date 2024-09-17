#!/usr/bin/env python3
# Copyright 2024 tmp
# See LICENSE file for licensing details.

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest
import yaml
from pytest_operator.plugin import OpsTest

import charm

if TYPE_CHECKING:
    from juju.model import Model

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./charmcraft.yaml").read_text())
APP_NAME = METADATA["name"]


@pytest.mark.skip_if_deployed
@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest):
    """Build and deploy calibre-web charm, attaching resources and storage.

    Fails sometimes on my machine due to failure to attach storage, but passes in a fresh VM.
    """
    # Build and deploy charm from local source folder
    charm = await ops_test.build_charm(".")
    # deploy and attach storage
    model = cast("Model", ops_test.model)
    resources = {
        "calibre-web-image": METADATA["resources"]["calibre-web-image"]["upstream-source"],
        "calibre-library": "./empty.zip",
    }
    await model.deploy(charm, resources=resources, application_name=APP_NAME)
    await model.wait_for_idle(apps=[APP_NAME], status="active", raise_on_blocked=True, timeout=600)


async def test_set_config(ops_test: OpsTest):
    model = cast("Model", ops_test.model)
    app = model.applications[APP_NAME]
    assert app is not None
    for behaviour in charm.LIBRARY_WRITE_BEHAVIOURS:
        await app.set_config({"library-write": behaviour})
        await model.wait_for_idle(
            apps=[APP_NAME],
            status="active",
            raise_on_error=True,
            raise_on_blocked=True,
            timeout=600,
        )
    behaviour = "bad"
    assert behaviour not in charm.LIBRARY_WRITE_BEHAVIOURS
    await app.set_config({"library-write": behaviour})
    await model.wait_for_idle(
        apps=[APP_NAME],
        status="blocked",
        raise_on_error=True,
        raise_on_blocked=False,
        timeout=600,
    )
