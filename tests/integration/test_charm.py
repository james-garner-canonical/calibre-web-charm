#!/usr/bin/env python3
# Copyright 2024 tmp
# See LICENSE file for licensing details.

import logging
from inspect import cleandoc
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
KNOWN_LIBRARY_INFO_OUTPUT: dict[Path, dict[charm.LibraryInfoFormat, str]] = {
    Path("files/library.zip"): {
        "ls-1": cleandoc(
            """
            John Schember
            metadata.db
            """
        ),
        "tree": cleandoc(
            """
            .
            ├── John Schember
            │   └── Quick Start Guide (1)
            │       ├── cover.jpg
            │       ├── metadata.opf
            │       └── Quick Start Guide - John Schember.epub
            └── metadata.db

            2 directories, 4 files
            """
        ),
    },
    Path("tests/library-austen-flat.zip"): {
        "ls-1": cleandoc(
            """
            Jane Austen
            John Schember
            metadata.db
            """
        ),
        "tree": cleandoc(
            """
            .
            ├── Jane Austen
            │   └── Pride and Prejudice (2)
            │       ├── cover.jpg
            │       ├── metadata.opf
            │       └── Pride and Prejudice - Jane Austen.epub
            ├── John Schember
            │   └── Quick Start Guide (1)
            │       ├── cover.jpg
            │       ├── metadata.opf
            │       └── Quick Start Guide - John Schember.epub
            └── metadata.db

            4 directories, 7 files
            """
        ),
    },
}
KNOWN_LIBRARY_INFO_OUTPUT.update(
    {Path("tests/library-austen-nested.zip"): KNOWN_LIBRARY_INFO_OUTPUT[Path("tests/library-austen-flat.zip")]}
)


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
    model, app, unit = get_model_app_unit(ops_test)
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
        await set_library_write_config(ops_test, behaviour=good_behaviour)


async def test_library_write_action_with_skip(ops_test: OpsTest):
    await add_books_sentinel(ops_test)
    await run_library_write_action(ops_test, behaviour="skip")
    # library-write: won't write, sentinel file will still be there
    await execute_in_container(ops_test, ["test", "-e", SENTINEL_PATH])
    # cleanup
    await execute_in_container(ops_test, ["rm", SENTINEL_PATH])
    await execute_in_container(ops_test, ["test", "!", "-e", SENTINEL_PATH])


async def test_library_write_action_with_clean(ops_test: OpsTest):
    await add_books_sentinel(ops_test)
    await run_library_write_action(ops_test, behaviour="clean")
    # library-write: will first clear /books/, sentinel file will be gone
    await execute_in_container(ops_test, ["test", "!", "-e", SENTINEL_PATH])


async def test_library_actions(ops_test: OpsTest):
    """Test writing new libraries and getting info about them.

    Test the following:
        - set library-write config to "clean"
        - attach a calibre-library resource
        - run the library-write action (removing old library)
        - run the library-info action with the different output formats
    For the libraries in KNOWN_LIBRARY_INFO_OUTPUT.
    """
    await set_library_write_config(ops_test, behaviour="clean")
    for library_path, output_formats in KNOWN_LIBRARY_INFO_OUTPUT.items():
        run_attach_calibre_library_resource(ops_test, path=library_path)
        await run_library_write_action(ops_test, behaviour="clean")
        for format, known_output in output_formats.items():
            result = await run_library_info_action(ops_test, format=format)
            assert result == known_output


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


def run_attach_calibre_library_resource(ops_test: OpsTest, path: str | Path) -> None:
    logger.debug(f"run_attach_calibre_library_resource(ops_test, {path=})")
    model, app, unit = get_model_app_unit(ops_test)
    with Path(path).open("rb") as file:
        app.attach_resource(resource_name="calibre-library", file_name=str(path), file_obj=file)


async def add_books_sentinel(ops_test: OpsTest) -> None:
    logger.debug("add_books_sentinel(ops_test)")
    await execute_in_container(ops_test, ["touch", SENTINEL_PATH])
    await execute_in_container(ops_test, ["test", "-e", SENTINEL_PATH])


async def execute_in_container(ops_test: OpsTest, command: list[str]) -> None:
    logger.debug(f"execute_in_container(ops_test, {command=})")
    model, app, unit = get_model_app_unit(ops_test)
    args = ["juju", "ssh", f"--container={charm.CONTAINER_NAME}", str(unit.name), *command]
    return_code, stdout, stderr = await ops_test.run(*args, check=True)


async def run_library_info_action(ops_test: OpsTest, format: charm.LibraryInfoFormat) -> str:
    logger.debug(f"run_library_info_action(ops_test, {format=})")
    model, app, unit = get_model_app_unit(ops_test)
    params = {charm.LIBRARY_INFO_FORMAT_PARAM: format}
    action = cast("Action", await unit.run_action("library-info", **params))
    await action.wait()
    assert action.status == "completed"
    return action.results[format].strip()


async def run_library_write_action(ops_test: OpsTest, behaviour: charm.LibraryWriteBehaviour | None = None) -> None:
    logger.debug(f"run_library_write_action(ops_test, {behaviour=})")
    model, app, unit = get_model_app_unit(ops_test)
    if behaviour is not None:
        await set_library_write_config(ops_test, behaviour=behaviour)
    action = cast("Action", await unit.run_action("library-write"))
    await action.wait()
    assert action.status == "completed"
    assert action.results[charm.LIBRARY_WRITE_ACTION] == behaviour


async def set_library_write_config(ops_test: OpsTest, behaviour: str) -> None:
    logger.debug(f"set_library_write_config(ops_test, {behaviour=})")
    model, app, unit = get_model_app_unit(ops_test)
    model, app, unit = get_model_app_unit(ops_test)
    await app.set_config({"library-write": behaviour})
    await model.wait_for_idle(apps=[APP_NAME], status="active", raise_on_error=True, timeout=600)
