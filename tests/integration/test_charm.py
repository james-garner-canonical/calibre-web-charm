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
    from juju.action import Action
    from juju.application import Application
    from juju.model import Model
    from juju.unit import Unit

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./charmcraft.yaml").read_text())
APP_NAME = METADATA["name"]
SENTINEL_PATH = "/books/sentinel"


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


async def test_status_for_set_config(ops_test: OpsTest):
    model = cast("Model", ops_test.model)
    app = model.applications[APP_NAME]
    assert app is not None
    bad_behaviour = "bad"
    assert bad_behaviour not in charm.LIBRARY_WRITE_BEHAVIOURS
    await app.set_config({"library-write": bad_behaviour})
    await model.wait_for_idle(
        apps=[APP_NAME],
        status="blocked",
        raise_on_error=True,
        timeout=600,
    )
    for good_behaviour in charm.LIBRARY_WRITE_BEHAVIOURS:
        await app.set_config({"library-write": good_behaviour})
        await model.wait_for_idle(
            apps=[APP_NAME],
            status="active",
            raise_on_error=True,
            timeout=600,
        )


async def test_library_write_with_skip(ops_test: OpsTest):
    await add_books_sentinel(ops_test)
    await run_library_write_action(ops_test, behaviour="skip")
    # library-write: won't write, sentinel file will still be there
    await execute_in_container(ops_test, ["test", "-e", SENTINEL_PATH])
    # cleanup
    await execute_in_container(ops_test, ["rm", SENTINEL_PATH])
    await execute_in_container(ops_test, ["test", "!", "-e", SENTINEL_PATH])


async def test_library_write_with_clean(ops_test: OpsTest):
    await add_books_sentinel(ops_test)
    await run_library_write_action(ops_test, behaviour="clean")
    # library-write: will first clear /books/, sentinel file will be gone
    await execute_in_container(ops_test, ["test", "!", "-e", SENTINEL_PATH])


###########
# helpers #
###########


def get_model_app_unit(ops_test: OpsTest) -> tuple["Model", "Application", "Unit"]:
    model = cast("Model", ops_test.model)
    app = cast("Application", model.applications[APP_NAME])
    assert app is not None
    unit = cast("Unit", app.units[0])
    assert unit is not None
    return model, app, unit


async def add_books_sentinel(ops_test: OpsTest) -> None:
    await execute_in_container(ops_test, ["touch", SENTINEL_PATH])
    await execute_in_container(ops_test, ["test", "-e", SENTINEL_PATH])


async def run_library_write_action(ops_test: OpsTest, behaviour: charm.LibraryWriteBehaviour) -> None:
    model, app, unit = get_model_app_unit(ops_test)
    await app.set_config({"library-write": behaviour})
    await model.wait_for_idle(
        apps=[APP_NAME],
        status="active",
        raise_on_error=True,
        timeout=600,
    )
    action = cast("Action", await unit.run_action("library-write"))
    await action.wait()
    assert action.status == "completed"
    assert action.results[charm.LIBRARY_WRITE_ACTION] == behaviour


async def execute_in_container(ops_test: OpsTest, command: list[str]) -> None:
    model, app, unit = get_model_app_unit(ops_test)
    args = ["juju", "ssh", f"--container={charm.CONTAINER_NAME}", str(unit.name), *command]
    return_code, stdout, stderr = await ops_test.run(*args, check=True)
