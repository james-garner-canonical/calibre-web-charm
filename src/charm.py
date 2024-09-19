#!/usr/bin/env python3
# Copyright 2024 Canonical
# See LICENSE file for licensing details.

"""Charm the calibre-web application."""

import logging
import typing
from pathlib import Path
from typing import cast

import ops

logger = logging.getLogger(__name__)

CONTAINER_NAME = 'calibre-web'
SERVICE_NAME = 'calibre-web'
STORAGE_NAME = 'books'
LIBRARY_WRITE_ACTION = 'library-write'
LIBRARY_WRITE_CONFIG = 'library-write'
LIBRARY_INFO_ACTION = 'library-info'
LIBRARY_INFO_FORMAT_PARAM = 'format'

LibraryInfoFormat: typing.TypeAlias = typing.Literal['tree', 'ls-1']
LIBRARY_INFO_FORMATS = typing.get_args(LibraryInfoFormat)

LibraryWriteBehaviour: typing.TypeAlias = typing.Literal['skip', 'clean']
LIBRARY_WRITE_BEHAVIOURS = typing.get_args(LibraryWriteBehaviour)


CalibreWebLayerDict = typing.TypedDict(
    'CalibreWebLayerDict',
    {
        'summary': str,
        'description': str,
        'services': dict[str, ops.pebble.ServiceDict],
    },
    total=True,
)


class CalibreWebCharm(ops.CharmBase):
    """Charm the calibre-web application."""

    def __init__(self, framework: ops.Framework) -> None:
        super().__init__(framework)
        framework.observe(self.on.collect_unit_status, self._on_collect_status)
        framework.observe(self.on[CONTAINER_NAME].pebble_ready, self._on_pebble_ready)
        framework.observe(self.on[STORAGE_NAME].storage_attached, self._on_storage_attached)
        framework.observe(self.on.install, self._on_install)
        framework.observe(self.on.config_changed, self._on_config_changed)
        framework.observe(self.on[LIBRARY_WRITE_ACTION].action, self._on_library_write)
        framework.observe(self.on[LIBRARY_INFO_ACTION].action, self._on_library_info)

    def _on_install(self, event: ops.InstallEvent) -> None:
        """Perform one time setup.

        install happens after storage-attached
        """
        self.unit.set_ports(8083)

    def _on_collect_status(self, event: ops.CollectStatusEvent) -> None:
        logger.debug("_on_collect_status")
        event.add_status(ops.ActiveStatus())
        _, status = self._get_library_write_behaviour()
        event.add_status(status)

    def _on_pebble_ready(self, event: ops.PebbleReadyEvent) -> None:
        """Define and start the workload using the Pebble API.

        pebble-ready happens after install
        """
        logger.debug("_on_pebble_ready")
        container = event.workload
        container.add_layer(SERVICE_NAME, {**self.get_pebble_layer()}, combine=True)
        container.replan()
        logger.debug("_on_pebble_ready: installing dependencies")
        container.exec(['apt', 'update']).wait()
        container.exec(['apt', 'install', 'dtrx', 'tree', '-y']).wait()
        self._push_library_to_storage()

    def _on_storage_attached(self, event: ops.StorageAttachedEvent) -> None:
        #self._push_library_to_storage()
        pass

    def _on_config_changed(self, event: ops.ConfigChangedEvent):
        """Don't do anything! User can run library-write action if needed.

        Bad config values are handled in _on_collect_status

        _on_collect_status will be called regardless of whether we observe
        config-changed, but this might change someday ...
        """
        pass

    def _on_library_write(self, event: ops.ActionEvent) -> None:
        library_write_behaviour, status = self._get_library_write_behaviour()
        if library_write_behaviour is None:
            event.fail(status.message)
            return
        self._push_library_to_storage()
        event.set_results({LIBRARY_WRITE_CONFIG: library_write_behaviour})

    def _on_library_info(self, event: ops.ActionEvent) -> None:
        container = self.unit.get_container(CONTAINER_NAME)
        format = cast(str, event.params[LIBRARY_INFO_FORMAT_PARAM])
        match format:
            case 'tree':
                logger.debug('_on_library_info: tree: executing')
                process = container.exec(
                    ['tree'],
                    working_dir='/books/',
                    stdout=cast(typing.BinaryIO, (stdout := CaptureStdOut())),
                )
                process.wait()
                try:
                    event.set_results({'tree': '\n'.join(stdout.lines)})
                except OSError:
                    event.set_results({'tree': 'library size too large, try ls-1'})
            case 'ls-1':
                logger.debug('_on_library_info: tree: executing')
                process = container.exec(
                    ['ls', '-1'],
                    working_dir='/books/',
                    stdout=cast(typing.BinaryIO, (stdout := CaptureStdOut())),
                )
                process.wait()
                try:
                    event.set_results({'ls-1': '\n'.join(stdout.lines)})
                except OSError:
                    event.set_results({'ls-1': 'library size too large, sorry!'})
            case _:
                msg = (
                    f'Invalid value {format} for {LIBRARY_INFO_FORMAT_PARAM} parameter'
                    f' of {LIBRARY_INFO_ACTION} action.'
                )
                logger.error('_on_library_info: %s', msg)
                event.fail(msg)

    @staticmethod
    def get_pebble_layer() -> CalibreWebLayerDict:
        """Return a dictionary representing the Pebble layer."""
        c = ' && '.join(
            [
                'bash /etc/s6-overlay/s6-rc.d/init-calibre-web-config/run',
                # with bash because the run script shebang depends on s6
                'python3 /app/calibre-web/cps.py',
            ]
        )
        command = f"bash -c '{c}'"
        return {
            'summary': f'{SERVICE_NAME} layer',
            'description': f'pebble config layer for {SERVICE_NAME}',
            'services': {
                SERVICE_NAME: {
                    'override': 'replace',
                    'summary': 'calibre-web',
                    'command': command,
                    'startup': 'enabled',
                    'working-dir': '/app/calibre-web',
                    'environment': {
                        'PUID': '1000',  # copied from example docker run
                        'PGID': '1000',  # copied from example docker run
                        'TZ': 'Etc/UTC',  # copied from example docker run
                        'CALIBRE_DBPATH': '/config',
                    },
                }
            },
        }

    def _push_library_to_storage(self) -> None:
        """Push user provided or default calibre-library resource to storage."""
        logger.debug("_push_library_to_storage")
        library_write_behaviour, _ = self._get_library_write_behaviour()
        if library_write_behaviour is None:
            return
        container = self.framework.model.unit.containers[CONTAINER_NAME]
        if contents := container.list_files('/books/'):
            msg_prefix = f'_push_library_to_storage: {library_write_behaviour=}: '
            match library_write_behaviour:
                case 'skip':
                    logger.debug(msg_prefix + 'returning')
                    return
                case 'clean':
                    logger.debug(msg_prefix + 'cleaning ...')
                    for fileinfo in contents:
                        container.remove_path(fileinfo.path, recursive=True)
        logger.debug('_push_library_to_storage: container=%s', CONTAINER_NAME)
        library_path = Path(self.model.resources.fetch('calibre-library'))
        library = library_path.read_bytes()
        # if the default library 'resource' was the starter library.zip
        # instead of the empty empty.zip, this logic could be removed
        if len(library):  # user provided library
            logger.debug('_push_library_to_storage: library_path=%s', library_path)
            self._push_and_extract_library(container, library)
            return
        # else: use default library
        library_path = Path('.') / 'library.zip'
        library = library_path.read_bytes()
        assert library
        logger.debug('_push_library_to_storage: library_path=%s', library_path)
        self._push_and_extract_library(container, library)

    def _get_library_write_behaviour(
        self,
    ) -> tuple[LibraryWriteBehaviour, ops.ActiveStatus] | tuple[None, ops.BlockedStatus]:
        library_write_behaviour = self.config[LIBRARY_WRITE_CONFIG]
        if library_write_behaviour not in LIBRARY_WRITE_BEHAVIOURS:
            msg = f"invalid {LIBRARY_WRITE_CONFIG}: '{library_write_behaviour}'"
            return None, ops.BlockedStatus(msg)
        return cast(LibraryWriteBehaviour, library_write_behaviour), ops.ActiveStatus()

    def _push_and_extract_library(self, container: ops.Container, library: bytes) -> None:
        logger.debug('_push_and_extract_library: copying library')
        container.push('/books/library.zip', library)
        logger.debug('_push_and_extract_library: extracting library')
        # use dtrx to extract library due to its consistent behaviour over many archive types
        container.exec(
            ['dtrx', '--noninteractive', '--overwrite', 'library.zip'],
            working_dir='/books',
        ).wait()
        # dtrx always extracts into a folder named after the archive
        logger.debug('_push_and_extract_library: flattening /books/library/ to /books/')
        self._move_directory_contents_to_parent(container, directory='/books/library')
        container.remove_path('/books/library.zip')
        # library.zip may contain the library contents directly, or inside a 'Calibre Library' directory
        if container.exists('/books/Calibre Library'):
            logger.debug(
                '_push_and_extract_library: flattening /books/Calibre Library/ contents to /books'
            )
            self._move_directory_contents_to_parent(container, directory='/books/Calibre Library')
        logger.debug('_push_and_extract_library: done')

    def _move_directory_contents_to_parent(
        self, container: ops.Container, directory: Path | str
    ) -> None:
        directory = str(directory)
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
        container.exec(move_contents_up_one_level, working_dir=directory).wait()
        container.remove_path(directory, recursive=False)  # error if not empty


class CaptureStdOut:
    """Capture stdout when executing processes.

    The default stdout stream is often closed when we try to read it after a process completes.
    This captures stdout in a simple list for later reading.
    """

    def __init__(self):
        self.lines: list[str] = []

    def write(self, stuff: str) -> None:
        """Append write argument to self.lines."""
        self.lines.append(stuff)


if __name__ == '__main__':  # pragma: nocover
    ops.main(CalibreWebCharm)  # type: ignore
