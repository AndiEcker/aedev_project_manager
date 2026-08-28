<!-- THIS FILE IS EXCLUSIVELY MAINTAINED by the project aedev.aedev v0.3.34 -->
<!-- THIS FILE IS EXCLUSIVELY MAINTAINED by the project aedev.namespace_root_tpls v0.3.33 -->
# project_manager 0.3.37

[![GitLab develop](https://img.shields.io/gitlab/pipeline/aedev-group/aedev_project_manager/develop?logo=python)](
    https://gitlab.com/aedev-group/aedev_project_manager)
[![LatestPyPIrelease](
    https://img.shields.io/gitlab/pipeline/aedev-group/aedev_project_manager/release0.3.37?logo=python)](
    https://gitlab.com/aedev-group/aedev_project_manager/-/tree/release0.3.37)
[![PyPIVersions](https://img.shields.io/pypi/v/aedev_project_manager)](
    https://pypi.org/project/aedev-project-manager/#history)

>aedev namespace package portion project_manager: maintain Python projects locally and remotely.

[![Coverage](https://aedev-group.gitlab.io/aedev_project_manager/coverage.svg)](
    https://aedev-group.gitlab.io/aedev_project_manager/coverage/index.html)
[![MyPyPrecision](https://aedev-group.gitlab.io/aedev_project_manager/mypy.svg)](
    https://aedev-group.gitlab.io/aedev_project_manager/lineprecision.txt)
[![PyLintScore](https://aedev-group.gitlab.io/aedev_project_manager/pylint.svg)](
    https://aedev-group.gitlab.io/aedev_project_manager/pylint.log)

[![PyPIImplementation](https://img.shields.io/pypi/implementation/aedev_project_manager)](
    https://gitlab.com/aedev-group/aedev_project_manager/)
[![PyPIPyVersions](https://img.shields.io/pypi/pyversions/aedev_project_manager)](
    https://gitlab.com/aedev-group/aedev_project_manager/)
[![PyPIWheel](https://img.shields.io/pypi/wheel/aedev_project_manager)](
    https://gitlab.com/aedev-group/aedev_project_manager/)
[![PyPIFormat](https://img.shields.io/pypi/format/aedev_project_manager)](
    https://pypi.org/project/aedev-project-manager/)
[![PyPILicense](https://img.shields.io/pypi/l/aedev_project_manager)](
    https://gitlab.com/aedev-group/aedev_project_manager/-/blob/develop/LICENSE.md)
[![PyPIStatus](https://img.shields.io/pypi/status/aedev_project_manager)](
    https://libraries.io/pypi/aedev-project-manager)
[![PyPIDownloads](https://img.shields.io/pypi/dm/aedev_project_manager)](
    https://pypi.org/project/aedev-project-manager/#files)

## features

simplifies your programming workflow, in order to:

    * clone or fork projects from GitLab or GitHub
    * push bug fixes and new features of projects to GitLab or GitHub
    * request a MR (merge request) (or a PR (pull request) at GitHub)
    * publish packages to [PyPI](https://pypi.org) or [PyPI Test](https://test.pypi.org)
    * deploy Django apps to [PythonAnywhere](https://pythonanywhere.com)  
    * run resource checks (i18n, images, sounds)
    * run unit and integration tests (with coverage reports)
    * use templates to create and maintain code, resource and configuration files
    * bulk refresh/update of mulitple projects, e.g. your namespace portions projects (:pep:`420`)


## installation

execute the following command to install the
aedev.project_manager package
in the currently active virtual environment:
 
```shell script
pip install aedev-project-manager
```

if you want to contribute to this portion then first fork
[the aedev_project_manager repository at GitLab](
https://gitlab.com/aedev-group/aedev_project_manager "aedev.project_manager code repository").
after that pull it to your machine and finally execute the
following command in the root folder of this repository
(aedev_project_manager):

```shell script
pip install --editable .[dev]
```

this command installs this package portion project
along with the necessary tools to modify the source code,
run unit tests, and build documentation. to install only
the dependencies required for a specific task,  replace
`dev` with one of the following:

    * `tests`: for contributing to the unit test suite
    * `docs`: for maintaining and building documentation

more detailed explanations on how to contribute to this project
[are available here](
https://gitlab.com/aedev-group/aedev_project_manager/-/blob/develop/CONTRIBUTING.rst)


## namespace portion documentation

the documentation of the source code of this portion is available at
[ReadTheDocs](
https://aedev.readthedocs.io/en/latest/_autosummary/aedev.project_manager.html
"aedev_project_manager documentation").

check also the
[manual](https://aedev.readthedocs.io/en/latest/man/project_manager.html "project manager manual")
for more detailed information on the usage of the project manager tool and their provided workflows.

the [source code](https://gitlab.com/aedev-group/aedev_project_manager "project manager source code")
is maintained by the user group [aedev-group](https://gitlab.com/aedev-group).

this project is implemented in pure Python code and based on portions of the two namespaces
[__ae__ (Application Environment)](https://ae.readthedocs.io "ae namespace") and
[__aedev__ (Development Packages and Tools)](https://ae.readthedocs.io "aedev namespace").

