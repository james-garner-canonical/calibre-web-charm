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

CONTAINER_NAME = 'calibre-web'
STORAGE_NAME = 'books'
LIBRARY_WRITE_ACTION = 'library-write'
LIBRARY_WRITE_BEHAVIOUR_KEY = 'library-write'
GET_LIBRARY_ACTION = 'library-info'
GET_LIBRARY_FORMAT_PARAM = 'format'

GetLibraryFormatParamValue: typing.TypeAlias = typing.Literal['tree', 'ls-1']  # , 'zip']
GET_LIBRARY_FORMAT_PARAM_VALUES = typing.get_args(GetLibraryFormatParamValue)

LibraryWriteBehaviour: typing.TypeAlias = typing.Literal['skip', 'clean']  # , 'overwrite']
LIBRARY_WRITE_BEHAVIOURS = typing.get_args(LibraryWriteBehaviour)


class CalibreWebCharmCharm(ops.CharmBase):
    """Charm the service."""

    def __init__(self, framework: ops.Framework) -> None:
        super().__init__(framework)
        framework.observe(self.on[CONTAINER_NAME].pebble_ready, self._on_pebble_ready)
        framework.observe(self.on[STORAGE_NAME].storage_attached, self._on_storage_attached)
        framework.observe(self.on.config_changed, self._on_config_changed)
        framework.observe(self.on.collect_unit_status, self._on_collect_status)
        framework.observe(self.on[GET_LIBRARY_ACTION].action, self._on_library_info)
        framework.observe(self.on[LIBRARY_WRITE_ACTION].action, self._on_library_write)
        self.unit.set_ports(8083)

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
            "bash /etc/s6-overlay/s6-rc.d/init-calibre-web-config/run",
            # with bash because the run script shebang depends on s6
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

    def _on_library_info(self, event: ops.ActionEvent) -> None:
        format = cast(str, event.params[GET_LIBRARY_FORMAT_PARAM])
        if format not in GET_LIBRARY_FORMAT_PARAM_VALUES:
            msg = (
                f"Invalid value {format} for {GET_LIBRARY_FORMAT_PARAM} parameter"
                f" of {GET_LIBRARY_ACTION} action."
            )
            self._add_status(ops.BlockedStatus(msg))
            return
        format = cast(GetLibraryFormatParamValue, format)
        container = self.framework.model.unit.containers[CONTAINER_NAME]
        match format:
            case 'tree':
                try:
                    container.exec(['which', 'tree']).wait()
                except ops.pebble.ExecError:
                    logger.debug('_on_library_info: tree: installing dependencies')
                    container.exec(['apt', 'update']).wait()
                    container.exec(['apt', 'install', 'tree', '-y']).wait()
                logger.debug('_on_library_info: tree: executing')
                process = container.exec(
                    ['tree'],
                    working_dir='/books/',
                    stdout=cast(typing.BinaryIO, (stdout := CaptureStdOut())),
                )
                process.wait()
                event.set_results({'tree': '\n'.join(stdout.lines)})
            case 'ls-1':
                logger.debug('_on_library_info: tree: executing')
                process = container.exec(
                    ['ls', '-1'],
                    working_dir='/books/',
                    stdout=cast(typing.BinaryIO, (stdout := CaptureStdOut())),
                )
                process.wait()
                event.set_results({'ls-1': '\n'.join(stdout.lines)})
            #case 'zip':
            #    logger.debug('_on_library_info: zip: installing dependencies')
            #    container.exec(['apt', 'update']).wait()
            #    container.exec(['apt', 'install', 'zip', '-y']).wait()
            #    container.exec(
            #        ['zip', '-r', 'library.zip', './'],
            #        working_dir='/books/',
            #        stdout=cast(typing.BinaryIO, (stdout := CaptureStdOut())),
            #    ).wait()
            #    binary = container.pull('/books/library.zip', encoding=None).read()
            #    string = base64.encodebytes(binary)
            #    event.set_results({'zip': string})  # OSError: Argument list too long

    def _on_library_write(self, event: ops.ActionEvent) -> None:
        self._push_library_to_storage()

    def _on_storage_attached(self, event: ops.StorageAttachedEvent) -> None:
        self._push_library_to_storage()

    def _push_library_to_storage(self) -> None:
        """Push user provided or default calibre-library resource to storage."""
        try:
            library_write_behaviour = self._library_write_behaviour
        except ValueError:
            return
        container = self.framework.model.unit.containers[CONTAINER_NAME]
        if (contents := container.list_files('/books/')):
            msg_prefix = f"_push_library_to_storage: {library_write_behaviour=}: "
            match library_write_behaviour:
                case "skip":
                    logger.debug(msg_prefix + "returning")
                    return
                case "clean":
                    logger.debug(msg_prefix + "cleaning ...")
                    for fileinfo in contents:
                        container.remove_path(fileinfo.path, recursive=True)
                #case "overwrite":
                #    logger.debug(msg_prefix + "continuing ...")
        logger.debug(f"_push_library_to_storage: {container=}")
        library_path = Path(self.framework.model.resources.fetch('calibre-library'))
        library = library_path.read_bytes()
        if len(library):  # user provided library
            logger.debug(f"_push_library_to_storage: {library_path=}")
            self._push_and_extract_library(container, library)
            return
        #else: use default library
        library_path = Path('.') / 'library.zip'
        library = library_path.read_bytes()
        assert library
        logger.debug(f"_push_library_to_storage: {library_path=}")
        self._push_and_extract_library(container, library)

    def _push_and_extract_library(self, container: ops.Container, library: bytes) -> None:
        # use dtrx to extract library due to its consistent behaviour over many archive types
        # could just add dtrx to the docker image? but it's somehow nice to use the off the shelf image
        try:
            container.exec(['which', 'dtrx']).wait()
        except ops.pebble.ExecError:
            logger.debug("_push_and_extract_library: installing dependencies")
            container.exec(['apt', 'update']).wait()
            container.exec(['apt', 'install', 'dtrx', '-y']).wait()
        logger.debug("_push_and_extract_library: copying library")
        container.push('/books/library.zip', library)

        logger.debug("_push_and_extract_library: extracting library")
        container.exec(
            ['dtrx', '--noninteractive', '--overwrite', 'library.zip'],
            working_dir='/books',
        ).wait()

        logger.debug("_push_and_extract_library: flattening /books/library/ to /books/")
        # dtrx always extracts into a folder named after the archive
        move_contents_up_one_level = [
            'bash',
            '-c',
            (
                'shopt -s nullglob ; '
                'mv --force --target-directory=../ ./* ./.[!.]* '
                '|| true'  # ignore no matches in glob ... in addition to other errors >:(
                # mv will fail if any directories colide (--force doesn't overwrite dirs)
                # but they shouldn't since we only run this if we first clean /books/
            ),
        ]
        container.exec(move_contents_up_one_level, working_dir='/books/library').wait()
        #extra exec kwargs when debugging:
        #kwargs = dict(combine_stderr=True, stderr=None, stdout=cast(typing.BinaryIO, (stdout := CaptureStdOut())))
        container.exec(['rmdir',  '/books/library']).wait()  # error if not empty
        container.remove_path('/books/library.zip')

        # library.zip may contain the library contents directly, or inside a 'Calibre Library' directory
        if container.exists('/books/Calibre Library'):
            logger.debug(
                "_push_and_extract_library: flattening /books/Calibre Library/ contents to /books"
            )
            container.exec(move_contents_up_one_level, working_dir='/books/Calibre Library').wait()
            container.exec(['rmdir', '/books/Calibre Library']).wait()  # error if not empty
        logger.debug("push_and_extract_library: done")

    def _on_config_changed(self, event: ops.ConfigChangedEvent):
        """Handle changed configuration."""
        logger.debug("_on_config_changed")
        self._push_library_to_storage()

    @property
    def _library_write_behaviour(self) -> LibraryWriteBehaviour:
        library_write_behaviour = cast(str, self.model.config[LIBRARY_WRITE_BEHAVIOUR_KEY]).lower()
        if library_write_behaviour not in LIBRARY_WRITE_BEHAVIOURS:
            msg = f"invalid {LIBRARY_WRITE_BEHAVIOUR_KEY}: '{library_write_behaviour}'"
            self._add_status(ops.BlockedStatus(msg))
            raise ValueError(msg)
        return cast(LibraryWriteBehaviour, library_write_behaviour)

    def _on_collect_status(self, event: ops.CollectStatusEvent) -> None:
        try:
            self._library_write_behaviour
        except ValueError:
            pass
        event.add_status(ops.ActiveStatus())

    def _add_status(self, status: ops.StatusBase) -> None:
        """Dirty hack to add status outside _on_collect_status for auto prioritisation."""
        event = ops.CollectStatusEvent(ops.Handle(parent=None, key=None, kind="whatever"))
        event.framework = self.framework
        event.add_status(status)


class CaptureStdOut:
    """Capture stdout when executing processes.

    The default stdout stream is often closed when we try to read it after a process completes.
    This captures stdout in a simple list for later reading.
    """

    def __init__(self):
        self.lines: list[str] = []

    def write(self, stuff: str) -> None:
        self.lines.append(stuff)


if __name__ == "__main__":  # pragma: nocover
    ops.main(CalibreWebCharmCharm)  # type: ignore
