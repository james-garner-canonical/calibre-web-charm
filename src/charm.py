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
from pathlib import Path
from typing import cast

import ops

# Log messages can be retrieved using juju debug-log
logger = logging.getLogger(__name__)

VALID_LOG_LEVELS = ["info", "debug", "warning", "error", "critical"]

CALIBRE_WEB_CONTAINER = 'calibre-web'
STORAGE_NAME = 'books'


class CalibreWebCharmCharm(ops.CharmBase):
    """Charm the service."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on[CALIBRE_WEB_CONTAINER].pebble_ready, self._on_pebble_ready)
        framework.observe(self.on[STORAGE_NAME].storage_attached, self._on_storage_attached)
        self.unit.set_ports(8083)
        #framework.observe(self.on.config_changed, self._on_config_changed)

    def _on_pebble_ready(self, event: ops.PebbleReadyEvent):
        """Define and start a workload using the Pebble API.

        Change this example to suit your needs. You'll need to specify the right entrypoint and
        environment configuration for your specific workload.

        Learn more about interacting with Pebble at at https://juju.is/docs/sdk/pebble.
        """
        # Get a reference the container attribute on the PebbleReadyEvent
        container = event.workload
        # Add initial Pebble config layer using the Pebble API
        container.add_layer("calibre-web", self._pebble_layer, combine=True)
        # Make Pebble reevaluate its plan, ensuring any services are started if enabled.
        container.replan()
        # Learn more about statuses in the SDK docs:
        # https://juju.is/docs/sdk/constructs#heading--statuses
        self.unit.status = ops.ActiveStatus()

    def _on_storage_attached(self, event: ops.StorageAttachedEvent):
        def push_and_extract_library(container: ops.Container, library: bytes):
            logger.debug("_on_storage_attached: push_and_extract_library")
            logger.debug("push_and_extract_library: installing dependencies")
            container.exec(['apt', 'update']).wait()
            container.exec(['apt', 'install', 'dtrx', '-y']).wait()
            logger.debug("push_and_extract_library: copying library")
            container.push('/books/library.zip', library)
            container.exec(['dtrx', '--noninteractive', 'library.zip'], working_dir='/books').wait()
            container.exec(['bash', '-c', 'mv /books/library/* /books/']).wait()
            container.exec(['rm', '/books/library.zip']).wait()
            container.exec(['rmdir',  '/books/library']).wait()
            logger.debug("push_and_extract_library: done")

        logger.debug("_on_storage_attached")
        container = self.framework.model.unit.containers[CALIBRE_WEB_CONTAINER]
        logger.debug(f"_on_storage_attached: {container=}")
        library_path = Path(self.framework.model.resources.fetch('calibre-library'))
        library = library_path.read_bytes()
        if len(library):  # user provided library
            logger.debug(f"_on_storage_attached: {library_path=}")
            push_and_extract_library(container, library)
        else:  # default library
            library_path = Path('.') / 'library.zip'
            logger.debug(f"_on_storage_attached: {library_path=}")
            library = library_path.read_bytes()
            assert library
            push_and_extract_library(container, library)
        if container.exists('/books/Calibre Library'):  # as a result of a push_and_extract
            logger.debug("_on_storage_attached: moving /books/Calibre Library contents to /books")
            container.exec(
                ['bash', '-c', 'mv --force ./* ./.[!.]* /books/'],
                working_dir='/books/Calibre Library',
            )
            container.exec(['rmdir', '/books/Calibre Library'])

            #class FakeOut:
            #    def __init__(self):
            #        self.lines = []
            #    def write(self, stuff):
            #        self.lines.append(stuff)
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
                        'PUID': 1000,  # copied from example docker run
                        'PGID': 1000,  # copied from example docker run
                        'TZ': 'Etc/UTC',  # copied from example docker run
                    },
                    'restart': 'unless-stopped',
                }
            },
        }


if __name__ == "__main__":  # pragma: nocover
    ops.main(CalibreWebCharmCharm)  # type: ignore
