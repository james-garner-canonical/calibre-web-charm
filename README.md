# calibre-web

`calibre-web` requires an initial calibre library to work with. This charm attaches some storage and writes a library to it once the storage is attached -- either a library provided at deployment time as a resource, or a starter library if an empty file is passed as the resource.

To run the local charm:
```bash
juju deploy ./calibre-web_ubuntu-22.04-amd64.charm \
    --resource calibre-web-image=lscr.io/linuxserver/calibre-web@sha256:b9082211440a374e2d30450135c1ce22b2d8239e1c6185443f1bf51b85a2f5c1 \
    --resource calibre-library=./empty.zip  # an empty file
```

The user's library can be provided as a resource, at deployment, or e.g.
```bash
juju attach-resource calibre-web calibre-library=$ZIPPED_USER_LIBRARY
```

Whether to replace any existing library in storage can be configured, either at deployment or e.g.
```bash
juju config calibre-web library-write=clean  # delete any existing library first
juju config calibre-web library-write=skip  # do nothing if there's already a library
```

Actions can be run to rewrite the library (e.g. after updating config), or to query the current library in a couple of formats.
```bash
juju run calibre-web/0 library-write

juju run calibre-web/0 library-info format=ls-1 --wait=1m
juju run calibre-web/0 library-info format=tree --wait=1m
```

You can connect to the running `calibre-web` at `$APP_IP:8083`. The default credentials are `admin` and `admin123`. The library locations `/books` needs to be entered on the following screen before further options will be available.
