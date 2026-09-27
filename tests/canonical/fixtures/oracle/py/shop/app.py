import subprocess

from flask import Flask, request

app = Flask(__name__)


def sanitize(value):
    return value.replace(";", "")


def run_report(name):
    return subprocess.run(["report", name], check=False)


@app.route("/report")
def report_view():
    name = request.args.get("name")
    return run_report(name)


@app.route("/safe")
def safe_view():
    name = sanitize(request.args.get("name"))
    return run_report(name)
