#!/usr/bin/env python

from __future__ import (absolute_import, print_function, division, unicode_literals)
from contextlib import contextmanager
from os.path import dirname, realpath, join, exists, normpath
import os
import shutil
import subprocess
import glob
import re
from shlex import split
import click

# https://virtualenv.pypa.io/en/latest/userguide.html#windows-notes
# scripts and executables on Windows go in ENV\Scripts\ instead of ENV/bin/
if os.name == "nt":
    venv_bin = "Scripts"
else:
    venv_bin = "bin"

root_dir = join(dirname(realpath(__file__)), "..", "..")
mitmproxy_dir = join(root_dir, "mitmproxy")
dist_dir = join(mitmproxy_dir, "dist")
test_venv_dir = join(root_dir, "venv.mitmproxy-release")

all_projects = ("netlib", "pathod", "mitmproxy")
tools = {
    "mitmproxy": ["mitmproxy", "mitmdump", "mitmweb"],
    "pathod": ["pathod", "pathoc"],
    "netlib": []
}
if os.name == "nt":
    tools["mitmproxy"].remove("mitmproxy")
version_files = {
    "mitmproxy": normpath(join(root_dir, "mitmproxy/libmproxy/version.py")),
    "pathod": normpath(join(root_dir, "pathod/libpathod/version.py")),
    "netlib": normpath(join(root_dir, "netlib/netlib/version.py")),
}


@contextmanager
def empty_pythonpath():
    """
    Make sure that the regular python installation is not on the python path,
    which would give us access to modules installed outside of our virtualenv.
    """
    pythonpath = os.environ["PYTHONPATH"]
    os.environ["PYTHONPATH"] = ""
    yield
    os.environ["PYTHONPATH"] = pythonpath


@contextmanager
def chdir(path):
    old_dir = os.getcwd()
    os.chdir(path)
    yield
    os.chdir(old_dir)


@click.group(chain=True)
def cli():
    """
    mitmproxy build tool
    """
    pass


@cli.command("contributors")
def contributors():
    """
    Update CONTRIBUTORS.md
    """
    print("Updating CONTRIBUTORS.md...")
    contributors_data = subprocess.check_output(split("git shortlog -n -s"))
    with open(join(mitmproxy_dir, "CONTRIBUTORS"), "w") as f:
        f.write(contributors_data)


@cli.command("docs")
def docs():
    """
    Render the docs
    """
    print("Rendering the docs...")
    subprocess.check_call([
        "cshape",
        join(mitmproxy_dir, "doc-src"),
        join(mitmproxy_dir, "doc")
    ])


@cli.command("set-version")
@click.option('--project', '-p', 'projects', multiple=True, type=click.Choice(all_projects), default=all_projects)
@click.argument('version')
def set_version(projects, version):
    """
    Update version information
    """
    print("Update versions...")
    version = ", ".join(version.split("."))
    for project, version_file in version_files.items():
        if project not in projects:
            continue
        print("Update %s..." % version_file)
        with open(version_file, "rb") as f:
            content = f.read()
        new_content = re.sub(r"IVERSION\s*=\s*\([\d,\s]+\)", "IVERSION = (%s)" % version, content)
        with open(version_file, "wb") as f:
            f.write(new_content)


@cli.command("git")
@click.option('--project', '-p', 'projects', multiple=True, type=click.Choice(all_projects), default=all_projects)
@click.argument('args', nargs=-1, required=True)
def git(projects, args):
    """
    Run a git command on every project
    """
    args = ["git"] + list(args)
    for project in projects:
        print("%s> %s..." % (project, " ".join(args)))
        subprocess.check_call(
            args,
            cwd=join(root_dir, project)
        )


@cli.command("sdist")
@click.option('--project', '-p', 'projects', multiple=True, type=click.Choice(all_projects), default=all_projects)
def sdist(projects):
    """
    Build a source distribution
    """
    with empty_pythonpath():
        print("Building release...")
        if exists(dist_dir):
            shutil.rmtree(dist_dir)
        for project in projects:
            print("Creating %s source distribution..." % project)
            subprocess.check_call(
                ["python", "./setup.py", "-q", "sdist", "--dist-dir", dist_dir, "--formats=gztar"],
                cwd=join(root_dir, project)
            )


@cli.command("test")
@click.option('--project', '-p', 'projects', multiple=True, type=click.Choice(all_projects), default=all_projects)
@click.pass_context
def test(ctx, projects):
    """
    Test the source distribution
    """
    if not exists(dist_dir):
        ctx.invoke(sdist)

    with empty_pythonpath():
        print("Creating virtualenv for test install...")
        if exists(test_venv_dir):
            shutil.rmtree(test_venv_dir)
        subprocess.check_call(["virtualenv", "-q", test_venv_dir])

        pip = join(test_venv_dir, venv_bin, "pip")
        with chdir(dist_dir):
            for project in projects:
                print("Installing %s..." % project)
                dist = glob.glob("./%s*" % project)[0]
                subprocess.check_call([pip, "install", "-q", dist])

            print("Running binaries...")
            for project in projects:
                for tool in tools[project]:
                    tool = join(test_venv_dir, venv_bin, tool)
                    print(tool)
                    print(subprocess.check_output([tool, "--version"]))

            print("Virtualenv available for further testing:")
            print("source %s" % normpath(join(test_venv_dir, venv_bin, "activate")))


@cli.command("upload")
@click.option('--username', prompt=True)
@click.password_option(confirmation_prompt=False)
@click.option('--repository', default="pypi")
def upload_release(username, password, repository):
    """
    Upload source distributions to PyPI
    """
    print("Uploading distributions...")
    subprocess.check_call([
        "twine",
        "upload",
        "-u", username,
        "-p", password,
        "-r", repository,
        "%s/*" % dist_dir
    ])


# TODO: Fully automate build process.
# This wizard is missing OSX builds and updating mitmproxy.org.
@cli.command("wizard")
@click.option('--version', prompt=True)
@click.option('--username', prompt="PyPI Username")
@click.password_option(confirmation_prompt=False, prompt="PyPI Password")
@click.option('--repository', default="pypi")
@click.option('--project', '-p', 'projects', multiple=True, type=click.Choice(all_projects), default=all_projects)
@click.pass_context
def wizard(ctx, version, username, password, repository, projects):
    """
    Interactive Release Wizard
    """
    for project in projects:
        if subprocess.check_output(["git", "status", "--porcelain"], cwd=join(root_dir, project)):
            raise RuntimeError("%s repository is not clean." % project)

    # Build test release
    ctx.invoke(sdist, projects=projects)
    ctx.invoke(test, projects=projects)
    click.confirm("Please test the release now. Is it ok?", abort=True)

    # bump version, update docs and contributors
    ctx.invoke(set_version, version=version, projects=projects)
    ctx.invoke(docs)
    ctx.invoke(contributors)

    # version bump commit + tag
    ctx.invoke(git, args=["commit", "-a", "-m", "bump version"], projects=projects)
    ctx.invoke(git, args=["tag", "v" + version], projects=projects)
    ctx.invoke(git, args=["push"], projects=projects)
    ctx.invoke(git, args=["push", "--tags"], projects=projects)

    # Re-invoke sdist with bumped version
    ctx.invoke(sdist, projects=projects)
    click.confirm("All good, can upload to PyPI?", abort=True)
    ctx.invoke(upload_release, username=username, password=password, repository=repository)
    click.echo("All done!")


if __name__ == "__main__":
    cli()
