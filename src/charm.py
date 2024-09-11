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
from typing import cast

import ops

# Log messages can be retrieved using juju debug-log
logger = logging.getLogger(__name__)

VALID_LOG_LEVELS = ["info", "debug", "warning", "error", "critical"]

CALIBRE_WEB_CONTAINER = 'calibre-web'


class CalibreWebCharmCharm(ops.CharmBase):
    """Charm the service."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(
            self.on[CALIBRE_WEB_CONTAINER].pebble_ready, self._on_calibre_web_pebble_ready
        )
        #framework.observe(
        #    self.on[CALIBRE_CONTAINER].pebble_ready, self._on_calibre_pebble_ready
        #)
        self.unit.set_ports(8083)
        #framework.observe(self.on.config_changed, self._on_config_changed)

    def _on_calibre_web_pebble_ready(self, event: ops.PebbleReadyEvent):
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
