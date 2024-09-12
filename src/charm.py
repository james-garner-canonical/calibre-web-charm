#!/usr/bin/env python3
# Copyright 2024 tmp
# See LICENSE file for licensing details.
#
# Learn more at: https://juju.is/docs/sdk

"""Charm the service.

Refer to the following tutorial that will help you
develop a new k8s charm using the Operator Framework:

https://juju.is/docs/sdk/create-a-minimal-kubernetes-charm
"""

import logging
import typing
from pathlib import Path
from typing import cast

import ops

# Log messages can be retrieved using juju debug-log
logger = logging.getLogger(__name__)

VALID_LOG_LEVELS = ["info", "debug", "warning", "error", "critical"]

CALIBRE_WEB_CONTAINER = 'calibre-web'
STORAGE_NAME = 'books'


class CaptureStdOut:
    """For debugging."""

    def __init__(self):
        self.lines: list[str] = []

    def write(self, stuff: str) -> None:
        self.lines.append(stuff)


class CalibreWebCharmCharm(ops.CharmBase):
    """Charm the service."""

    def __init__(self, framework: ops.Framework) -> None:
        super().__init__(framework)
        framework.observe(self.on[CALIBRE_WEB_CONTAINER].pebble_ready, self._on_pebble_ready)
        framework.observe(self.on[STORAGE_NAME].storage_attached, self._on_storage_attached)
        self.unit.set_ports(8083)
        #framework.observe(self.on.config_changed, self._on_config_changed)

    def _on_pebble_ready(self, event: ops.PebbleReadyEvent) -> None:
        """Define and start a workload using the Pebble API."""
        container = event.workload
        container.add_layer("calibre-web", self._pebble_layer, combine=True)
        container.replan()
        self.unit.status = ops.ActiveStatus()

    @property
    def _pebble_layer(self) -> ops.pebble.LayerDict:
        """Return a dictionary representing a Pebble layer."""
        c = " && ".join([
            "bash /etc/s6-overlay/s6-rc.d/init-calibre-web-config/run",  # with bash because the shebang depends on s6
            "export CALIBRE_DBPATH=/config",
            "cd /app/calibre-web",
            "python3 /app/calibre-web/cps.py",
        ])
        command = f"bash -c '{c}'"
        return {
            "summary": "calibre-web layer",
            "description": "pebble config layer for calibre-web",
            "services": {
                "calibre-web": {
                    "override": "replace",
                    "summary": "calibre-web",
                    "command": command,
                    "startup": "enabled",
                    "environment": {
                        'PUID': '1000',  # copied from example docker run
                        'PGID': '1000',  # copied from example docker run
                        'TZ': 'Etc/UTC',  # copied from example docker run
                    },
                    #'restart': 'unless-stopped',
                }
            },
        }

    def _on_storage_attached(self, event: ops.StorageAttachedEvent):
        """Push user provided or default calibre-library resource to storage."""
        container = self.framework.model.unit.containers[CALIBRE_WEB_CONTAINER]
        logger.debug(f"_on_storage_attached: {container=}")
        library_path = Path(self.framework.model.resources.fetch('calibre-library'))
        library = library_path.read_bytes()
        if len(library):  # user provided library
            logger.debug(f"_on_storage_attached: {library_path=}")
            self._push_and_extract_library(container, library)
        else:  # use default library
            library_path = Path('.') / 'library.zip'
            logger.debug(f"_on_storage_attached: {library_path=}")
            library = library_path.read_bytes()
            assert library
            self._push_and_extract_library(container, library)

    def _push_and_extract_library(self, container: ops.Container, library: bytes) -> None:
        logger.debug("_push_and_extract_library: installing dependencies")
        # use dtrx to extract library due to its consistent behaviour over many archive types
        # faster after the first time, but would it be faster to check for dtrx first?
        # alternatively just add dtrx to the docker image
        container.exec(['apt', 'update']).wait()
        container.exec(['apt', 'install', 'dtrx', '-y']).wait()

        logger.debug("_push_and_extract_library: copying library")
        container.push('/books/library.zip', library)

        logger.debug("_push_and_extract_library: extracting library")
        container.exec(
            ['dtrx', '--noninteractive', '--overwrite', 'library.zip'],
            working_dir='/books',
        ).wait()
        # dtrx always extracts into a folder named after the archive
        logger.debug("_push_and_extract_library: flattening /books/library/ to /books/")
        move_contents_up_one_level = [
            'bash',
            '-c',
            (
                'shopt -s nullglob ; '
                'mv --force --target-directory=../ ./* ./.[!.]* '
                '|| true'  # ignore no matches in glob
            )
        ]
        container.exec(move_contents_up_one_level, working_dir='/books/library').wait()
        #combine_stderr=True, stderr=None, stdout=cast(typing.BinaryIO, (stdout := CaptureStdOut())),
        container.exec(['rmdir',  '/books/library']).wait()
        container.exec(['rm', '/books/library.zip']).wait()

        # library.zip may contain the library contents directly, or inside a 'Calibre Library' directory
        if container.exists('/books/Calibre Library'):
            logger.debug(
                "_push_and_extract_library: flattening /books/Calibre Library/ contents to /books"
            )
            container.exec(move_contents_up_one_level, working_dir='/books/Calibre Library').wait()
            container.exec(['rmdir', '/books/Calibre Library']).wait()
        logger.debug("push_and_extract_library: done")

            #f = FakeOut()
            #try:
            #    logger.debug("moving all files to books, this normally fails")
            #    proc = container.exec(
            #        ['bash', '-c', 'mv --force ./* ./.[!.]* /books/'],
            #        working_dir='/books/Calibre Library',
            #        combine_stderr=True,
            #        stderr=None,
            #        stdout=f,
            #    )
            #    proc.wait()
            #except ops.pebble.ExecError as e:
            #    logger.debug("exception")
            #    logger.debug(e)
            #    logger.debug("it works tho ...")
            #    logger.debug(f.lines)
            #else:
            #    logger.debug("no exception")
            #f2 = FakeOut()
            #try:
            #    container.exec(
            #        ['rmdir', '/books/Calibre Library'],
            #        combine_stderr=True,
            #        stderr=None,
            #        stdout=f2,
            #    ).wait()
            #except ops.pebble.ExecError as e:
            #    logger.debug("exception")
            #    logger.debug(e)
            #    logger.debug(f2.lines)

    #def _on_config_changed(self, event: ops.ConfigChangedEvent):
    #    """Handle changed configuration.

    #    Change this example to suit your needs. If you don't need to handle config, you can remove
    #    this method.

    #    Learn more about config at https://juju.is/docs/sdk/config
    #    """
    #    # Fetch the new config value
    #    log_level = cast(str, self.model.config["log-level"]).lower()

    #    # Do some validation of the configuration option
    #    if log_level in VALID_LOG_LEVELS:
    #        # The config is good, so update the configuration of the workload
    #        container = self.unit.get_container("httpbin")
    #        # Verify that we can connect to the Pebble API in the workload container
    #        if container.can_connect():
    #            # Push an updated layer with the new config
    #            container.add_layer("httpbin", self._pebble_layer, combine=True)
    #            container.replan()

    #            logger.debug("Log level for gunicorn changed to '%s'", log_level)
    #            self.unit.status = ops.ActiveStatus()
    #        else:
    #            # We were unable to connect to the Pebble API, so we defer this event
    #            event.defer()
    #            self.unit.status = ops.WaitingStatus("waiting for Pebble API")
    #    else:
    #        # In this case, the config option is bad, so block the charm and notify the operator.
    #        self.unit.status = ops.BlockedStatus("invalid log level: '{log_level}'")


if __name__ == "__main__":  # pragma: nocover
    ops.main(CalibreWebCharmCharm)  # type: ignore
