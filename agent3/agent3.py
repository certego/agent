#!/usr/bin/env python
# Copyright (C) 2015-2019 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - http://www.cuckoosandbox.org
# See the file 'https://github.com/cuckoosandbox/cuckoo/blob/master/docs/LICENSE' for copying permission.

from flask import Flask
from flask import jsonify, request, send_file
import logging
import sys
import platform
import tempfile
import os
import stat
import shutil
import argparse
import zipfile
import subprocess

AGENT_VERSION = "1.0.0"
AGENT_FEATURES = [
    "execpy", "pinning", "logs", "largefile", "unicodepath",
]
state = {}
log = logging.getLogger()
log.setLevel(logging.DEBUG)
handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
log.addHandler(handler)


def create_app():
    app = Flask(__name__)

    @app.route("/")
    def get_index():
        return jsonify(message="Cuckoo Agent!", success=True, version=AGENT_VERSION, features=AGENT_FEATURES), 200

    @app.route("/status")
    def get_status():
        return jsonify(message="Analysis status", status=state.get("status"), description=state.get("description")), 200

    @app.route("/status", methods=["POST"])
    def put_status():
        if "status" not in request.form:
            return jsonify(message="No status has been provided"), 400

        state["status"] = request.form["status"]
        state["description"] = request.form.get("description")
        return jsonify(message="Analysis status updated"), 200

    @app.route("/logs")
    def get_logs():
        return jsonify(message="Agent logs", stdout=sys.stdout, stderr=sys.stderr), 200

    @app.route("/system")
    def get_system():
        return jsonify(message="System", system=platform.system()), 200

    @app.route("/environ")
    def get_environ():
        return jsonify(message="Environment variables", environ=dict(os.environ)), 200

    @app.route("/path")
    def get_path():
        return jsonify(message="Agent path", filepath=os.path.abspath(__file__)), 200

    @app.route("/mkdir", methods=["POST"])
    def do_mkdir():
        if "dirpath" not in request.form:
            return jsonify(message="No dirpath has been provided"), 400

        mode = int(request.form.get("mode", 0o777))

        try:
            os.makedirs(request.form["dirpath"], mode=mode)
        except (IOError, OSError, PermissionError, AttributeError, NameError) as e:
            log.debug(f"Cannot create directory: {e}")
            return jsonify(smessage="Error creating directory"), 500

        return jsonify(message="Successfully created directory"), 200

    @app.route("/mktemp", methods=["GET", "POST"])
    def do_mktemp():
        suffix = request.form.get("suffix", "")
        prefix = request.form.get("prefix", "tmp")
        dirpath = request.form.get("dirpath")

        try:
            fd, filepath = tempfile.mkstemp(suffix=suffix, prefix=prefix, dir=dirpath)
        except (IOError, OSError, PermissionError, AttributeError, NameError) as e:
            log.debug(f"Cannot create temp temporary file: {e}")
            return jsonify(message="Error creating temporary file"), 500

        os.close(fd)

        return jsonify(message="Successfully created temporary file", filepath=filepath), 200

    @app.route("/mkdtemp", methods=["GET", "POST"])
    def do_mkdtemp():
        suffix = request.form.get("suffix", "")
        prefix = request.form.get("prefix", "tmp")
        dirpath = request.form.get("dirpath")

        try:
            dirpath = tempfile.mkdtemp(suffix=suffix, prefix=prefix, dir=dirpath)
        except (IOError, OSError, PermissionError, AttributeError, NameError) as e:
            log.debug(f"Cannot create temp directory: {e}")
            return jsonify(message="Error creating temporary directory"), 500

        return jsonify(message="Successfully created temporary directory", dirpath=dirpath), 200

    @app.route("/store", methods=["POST"])
    def do_store():
        if "filepath" not in request.form:  # dst
            return jsonify(message="No filepath has been provided"), 400

        if "file" not in request.files:  # src
            return jsonify(message="No file has been provided"), 400

        file = request.files['file']
        file.save(request.form["filepath"])

        if not os.path.exists(request.form["filepath"]):
            log.debug(f"Cannot store file: {file.filename}")
            return jsonify(message="Error storing file"), 500

        return jsonify(message="Successfully stored file"), 200

    @app.route("/retrieve", methods=["POST"])
    def do_retrieve():
        if "filepath" not in request.form:
            return jsonify(message="No filepath has been provided"), 400

        if not os.path.exists(request.form["filepath"]):
            return jsonify(message="Path provided does not exist"), 404

        return send_file(request.form["filepath"])

    @app.route("/extract", methods=["POST"])
    def do_extract():
        if "dirpath" not in request.form:
            return jsonify(message="No dirpath has been provided"), 400

        if "zipfile" not in request.files:
            return jsonify(message="No zip file has been provided"), 400

        store_zip_path = tempfile.NamedTemporaryFile(suffix=".zip").name
        request.files["zipfile"].save(store_zip_path)

        try:
            with zipfile.ZipFile(store_zip_path, "r") as archive:
                archive.extractall(request.form["dirpath"])
        except zipfile.BadZipfile as e:
            log.debug(f"Cannot extract zip file: {e}")
            os.unlink(store_zip_path)
            return jsonify(message="Error extracting zip file"), 500
        except FileNotFoundError as e:
            log.debug(f"Destination path does not exist: {e}")
            os.unlink(store_zip_path)
            return jsonify(message="Destination path does not exist"), 500
        os.unlink(store_zip_path)
        return jsonify(message="Successfully extracted zip file"), 200

    @app.route("/remove", methods=["POST"])
    def do_remove():
        if "path" not in request.form:
            return jsonify(message="No path has been provided"), 400

        try:
            if os.path.isdir(request.form["path"]):
                # Mark all files as readable, so they can be deleted.
                for dirpath, _, filenames in os.walk(request.form["path"]):
                    for filename in filenames:
                        os.chmod(os.path.join(dirpath, filename), stat.S_IWRITE)
                shutil.rmtree(request.form["path"])
                message = "Successfully deleted directory"
            elif os.path.isfile(request.form["path"]):
                os.chmod(request.form["path"], stat.S_IWRITE)
                os.remove(request.form["path"])
                message = "Successfully deleted file"
            else:
                return jsonify(message="Path provided does not exist"), 404
        except (FileNotFoundError, OSError) as e:
            log.debug(f"Cannot remove file or directory: {e}")
            return jsonify(message="Error removing file or directory"), 500

        return jsonify(message=message), 200

    @app.route("/execute", methods=["POST"])
    def do_execute():
        if "command" not in request.form:
            return jsonify(message="No command has been provided"), 400

        # Execute the command asynchronously? As a shell command?
        is_async = "async" in request.form
        shell = "shell" in request.form

        cwd = request.form.get("cwd")
        stdout = stderr = p = None

        try:
            if is_async:
                subprocess.Popen(request.form["command"], shell=shell, cwd=cwd)
            else:
                p = subprocess.Popen(
                    request.form["command"], shell=shell, cwd=cwd,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE
                )
                stdout, stderr = p.communicate()  # str or bytes (doc)
                stdout = stdout if isinstance(stdout, str) else stdout.decode('utf8')
                stderr = stderr if isinstance(stderr, str) else stderr.decode('utf8')
        except subprocess.TimeoutExpired:
            p.kill()
            stdout, stderr = p.communicate()
            stdout = stdout if isinstance(stdout, str) else stdout.decode('utf8')
            stderr = stderr if isinstance(stderr, str) else stderr.decode('utf8')
            log.debug(f"Command timed out: {stdout} - {stderr}")
            return jsonify(message="Command timed out", stdout=stdout, stderr=stderr), 500
        except subprocess.SubprocessError as e:
            log.debug(f"Cannot execute command: {e}")
            return jsonify(message="Error executing command"), 500

        return jsonify(message="Successfully executed command", stdout=stdout, stderr=stderr), 200

    @app.route("/execpy", methods=["POST"])
    def do_execpy():
        if "filepath" not in request.form:
            return jsonify(message="No Python file has been provided"), 200

        # Execute the command asynchronously? As a shell command?
        is_async = "async" in request.form

        cwd = request.form.get("cwd")
        stdout = stderr = p = None

        proc_args = [
            sys.executable,
            request.form["filepath"],
        ]

        try:
            if is_async:
                subprocess.Popen(proc_args, cwd=cwd)
            else:
                p = subprocess.Popen(proc_args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                stdout, stderr = p.communicate()  # str or bytes (doc)
                stdout = stdout if isinstance(stdout, str) else stdout.decode('utf8')
                stderr = stderr if isinstance(stderr, str) else stderr.decode('utf8')
        except subprocess.TimeoutExpired:
            p.kill()
            stdout, stderr = p.communicate()
            stdout = stdout if isinstance(stdout, str) else stdout.decode('utf8')
            stderr = stderr if isinstance(stderr, str) else stderr.decode('utf8')
            log.debug(f"Python file timed out: {stdout} - {stderr}")
            return jsonify(message="Python file timed out", stdout=stdout, stderr=stderr), 500
        except subprocess.SubprocessError as e:
            log.debug(f"Cannot execute python file: {e}")
            return jsonify(message="Error executing python file"), 500

        return jsonify(message="Successfully executed python file", stdout=stdout, stderr=stderr), 200

    @app.route("/pinning")
    def do_pinning():
        if "client_ip" in state:
            return jsonify(message="Agent has already been pinned to an IP!"), 500

        state["client_ip"] = request.remote_addr
        return jsonify(message="Successfully pinned Agent", client_ip=request.remote_addr), 200

    @app.route("/kill")
    def do_kill():
        shutdown = request.environ.get("werkzeug.server.shutdown")
        if shutdown is None:
            return jsonify(message="Not running with the Werkzeug server"), 500

        shutdown()
        return jsonify(message="Quit the Cuckoo Agent"), 200

    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("host", nargs="?", default="0.0.0.0")
    parser.add_argument("port", nargs="?", default="8000")
    args = parser.parse_args()

    a = create_app()
    a.run(host=args.host, port=int(args.port))
