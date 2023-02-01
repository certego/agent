#!/usr/bin/env python
# Copyright (C) 2015-2019 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - http://www.cuckoosandbox.org
# See the file 'https://github.com/cuckoosandbox/cuckoo/blob/master/docs/LICENSE' for copying permission.

import os
import threading
import requests
import platform
import tempfile
from agent3.agent3 import create_app, AGENT_VERSION

# This whole setup is a bit ugly, but oh well.
host = "0.0.0.0"
port = 8000
app = create_app()
threading.Thread(group=None, target=app.run, name="agent3", kwargs={"host": host, "port": port}).start()


def http_get(uri, *args, **kwargs):
    return requests.get(
        "http://localhost:%s%s" % (port, uri), *args, **kwargs
    )


def http_post(uri, *args, **kwargs):
    return requests.post(
        "http://localhost:%s%s" % (port, uri), *args, **kwargs
    )


def test_index():
    assert http_get("/").json()["message"] == "Cuckoo Agent!"
    assert http_get("/").json()["version"] == AGENT_VERSION


def test_status():
    r = http_get("/status")
    assert r.status_code == 200
    assert r.json()["message"] == "Analysis status"
    assert r.json()["status"] is None
    assert r.json()["description"] is None

    assert http_post("/status").status_code == 400
    assert http_get("/status").json()["status"] is None

    assert http_post("/status", data={"status": "foo"}).status_code == 200
    r = http_get("/status").json()
    assert r["status"] == "foo"
    assert r["description"] is None

    assert http_post("/status", data={
        "status": "foo",
        "description": "bar",
    }).status_code == 200
    r = http_get("/status").json()
    assert r["status"] == "foo"
    assert r["description"] == "bar"


def test_system():
    assert http_get("/system").json()["system"] == platform.system()


def test_environ():
    assert http_get("/environ").json()


def test_mkdir():
    temp_dir = tempfile.TemporaryDirectory()

    assert http_post("/mkdir", data={
        "dirpath": os.path.join(temp_dir.name, "mkdir.test"),
    }).status_code == 200

    r = http_post("/remove", data={
        "path": os.path.join(temp_dir.name, "mkdir.test"),
    })
    assert r.status_code == 200
    assert r.json()["message"] == "Successfully deleted directory"

    assert http_post("/remove", data={
        "path": os.path.join(temp_dir.name, "mkdir.test"),
    }).status_code == 404

    os.rmdir(temp_dir.name)


def test_mktemp():
    r_fail = http_post("/mktemp", data={
        "dirpath": "/proc/non-existent",
    })
    assert r_fail.status_code == 500
    assert r_fail.json()["message"] == "Error creating temporary file"

    r_ok = http_post("/mktemp", data={
        "dirpath": "",  # this will work for windows test as well as linux
    })
    assert r_ok.status_code == 200
    assert r_ok.json()["message"] == "Successfully created temporary file"


def test_mkdtemp():
    r_fail = http_post("/mkdtemp", data={
        "dirpath": "/proc/non-existent",
    })
    assert r_fail.status_code == 500
    assert r_fail.json()["message"] == "Error creating temporary directory"

    r_ok = http_post("/mkdtemp", data={
        "dirpath": "",  # this will work for windows test as well as linux
    })
    assert r_ok.status_code == 200
    assert r_ok.json()["message"] == "Successfully created temporary directory"


def test_execute():
    assert http_post("/execute").status_code == 400


def test_zipfile():
    assert http_post("/extract").status_code == 400


def test_store():
    srcpath = os.path.join(os.getcwd(), "a.txt")
    dstpath = tempfile.NamedTemporaryFile(mode="w", dir=os.getcwd()).name

    if os.path.exists(srcpath):
        os.unlink(srcpath)

    if os.path.exists(dstpath):
        os.unlink(dstpath)

    f = open(srcpath, "w")
    f.write("A" * 1024 * 1024)
    f.close()
    f = open(srcpath, "rb")

    data = {
        "filepath": dstpath,
    }
    files = {
        "file": f,
    }
    assert http_post("/store", data=data, files=files).status_code == 200
    assert open(dstpath, "r").read() == "A" * 1024 * 1024

    os.unlink(srcpath)
    os.unlink(dstpath)


def test_store_unicode():
    srcpath = os.path.join(os.getcwd(), u"unic0de\u202e.txt")

    assert http_post("/store", data={
        "filepath": srcpath,
    }, files={
        "file": ("a.txt", "A" * 1024 * 1024),
    }).status_code == 200
    assert os.path.exists(srcpath)

    r = http_post("/retrieve", data={
        "filepath": srcpath,
    })
    assert r.status_code == 200
    assert r.content == bytes("A" * 1024 * 1024, 'ascii')
    assert os.path.exists(srcpath)

    assert http_post("/remove", data={
        "path": srcpath,
    }).status_code == 200
    assert not os.path.exists(srcpath)

    assert http_post("/remove", data={
        "path": srcpath,
    }).status_code == 404

    assert http_post("/retrieve", data={
        "filepath": srcpath,
    }).status_code == 404
