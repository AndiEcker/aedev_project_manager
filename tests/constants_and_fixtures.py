""" test constants and fixtures of the aedev.project_manager project. """
import contextlib
import os
import tempfile

from typing import Any, Optional, Union, cast
from unittest.mock import patch

import pytest

from ae.base import (
    DEF_PROJECT_PARENT_FOLDER, PY_INIT, PY_EXT,
    load_env_var_defaults, os_path_basename, os_path_isfile, os_path_join,
    read_file, write_file)
from ae.core import DEBUG_LEVEL_DISABLED, DEBUG_LEVEL_ENABLED, DEBUG_LEVEL_VERBOSE, main_app_instance
from ae.console import ConsoleApp

from aedev.base import DEF_MAIN_BRANCH, TEST_PROJECTS_REMOTE
from aedev.commands import in_prj_dir_venv, sh_exit_if_git_err
from aedev.project_vars import (
    ENV_VAR_NAME_PREFIX, PDV_NULL_VERSION, ProjectDevVars, increment_version)

from aedev.project_manager.utils import REGISTERED_HOSTS_CLASS_NAMES, get_app_option
from aedev.project_manager.templates import TPL_IMPORT_NAMES, template_path_option, template_version_option
from aedev.project_manager.__main__ import init_main, GithubCom, GitlabCom


# ---prepare unfinished/empty/changed namespace module/portion names&versions for unit tests (only on the local machine)

tst_ns_name = 'nsn'
tst_ns_por_pfx = 'tst_por_'                 # portion name prefix for changed_repo_path/empty_repo_path/module_repo_path
tst_imp_pfx = tst_ns_name + '.' + tst_ns_por_pfx
tst_pkg_pfx = tst_ns_name + '_' + tst_ns_por_pfx
tst_pkg_version = increment_version(PDV_NULL_VERSION)
tst_nxt_pgk_ver = increment_version(tst_pkg_version)

tst_root_prj_name = tst_ns_name + '_' + tst_ns_name
tst_namespaces_roots = [tst_ns_name + '.' + tst_ns_name]

tst_tpls_register = {}      # map of the 3 template registers used by the tests, initialized in setup_module()


# get contributor|ctb & maintainer|mtn credential/token (in env|config variables)
tst_ext_env = os.environ.copy()
load_env_var_defaults(".", tst_ext_env)  # use local machine pjm project user to get maintainer&contributor name/mail

tst_ctb_name = tst_ext_env.get('TEST_CONTRIBUTOR_NAME')
tst_ctb_token = tst_ext_env.get('TEST_CONTRIBUTOR_TOKEN')
# tst_ctb_email = tst_ext_env.get('TEST_CONTRIBUTOR_EMAIL')
# tst_ctb_root_url = f"https://oauth2:{tst_ctb_token}@{TEST_PROJECTS_REMOTE}/{tst_ctb_name}"

tst_mtn_name = tst_ext_env.get(ENV_VAR_NAME_PREFIX + 'AUTHOR')
tst_mtn_token = tst_ext_env.get('AE_OPTIONS_REPO_TOKEN_AT_GITLAB_COM') if tst_mtn_name != tst_ctb_name else ""
# tst_mtn_email = tst_ext_env.get(ENV_VAR_NAME_PREFIX + 'AUTHOR_EMAIL')
# ..root_url = f"https://oauth2:{tst_mtn_token}@{TEST_PROJECTS_REMOTE}/{TEST_PROJECTS_NAMESPACE}{PDV_REPO_GROUP_SUFFIX}"


debug_levels = [DEBUG_LEVEL_DISABLED, DEBUG_LEVEL_ENABLED, DEBUG_LEVEL_VERBOSE]
skip_if_not_maintainer = pytest.mark.skipif('not bool(tst_mtn_token)',
                                            reason=f"missing {TEST_PROJECTS_REMOTE} maintainer personal-access-token")


@pytest.fixture
def app_pjm(restore_app_env):
    """ provide project-manager-ConsoleApp instance that will be unregistered automatically """
    return init_main()


@pytest.fixture(params=debug_levels, ids=[f"debug_level=={_}" for _ in debug_levels])
def app_pjm_debug(request, app_pjm):
    print(f"\n>>> app_pjm_debug called with param={request.param}")
    app_pjm.parse_arguments = lambda *_args: None
    app_pjm.set_option('debug_level', request.param, save_to_config=False)

    return app_pjm


@pytest.fixture
def mocked_app_options():
    """ mock ConsoleApp option/config-var-setter/getter and option value requests via get_app_option/debug_or_verbose.

    main ConsoleApp instance argument parsing gets prevented by monkey-patching, e.g., of main_app.get_option().
    also direct access to pdv['main_app_options'] gets mocked by this fixture; useful to fix side effects
    of mocked child-pdv when option values should only be specified for the parent.

    to let ae.shell.debug_or_verbose() also behave like the value specified by the mocked option 'more_verbose',
    it will also get patched accordingly.
    """
    def _app_option(_pdv: ProjectDevVars, opt_nam: str) -> Optional[Any]:
        if opt_nam in mocked_options:
            return mocked_options[opt_nam]
        return get_app_option(_pdv, opt_nam)

    def _dbg_or_verbose():
        return mocked_options.get('more_verbose', False)

    main_app = cast(ConsoleApp, main_app_instance())
    ori_get_arg = main_app.get_argument
    ori_get_opt = main_app.get_option

    mocked_options: dict[str, Any] = {}
    mocked_options.update({template_path_option(import_name): ""
                           for import_name in tst_namespaces_roots + TPL_IMPORT_NAMES})
    mocked_options.update({template_version_option(import_name): ""
                           for import_name in tst_namespaces_roots + TPL_IMPORT_NAMES})

    main_app.get_argument = main_app.get_option = lambda opt: mocked_options.get(opt, None)

    with (patch('aedev.project_manager.utils.get_app_option', new=_app_option),
          patch('aedev.project_manager.__main__.get_app_option', new=_app_option),
          patch('aedev.project_manager.templates.get_app_option', new=_app_option),
          patch('ae.core.main_app_instance', return_value=main_app),
          patch('aedev.project_manager.__main__.debug_or_verbose', new=_dbg_or_verbose),
          patch('ae.shell.debug_or_verbose', new=_dbg_or_verbose),
          ):
        yield mocked_options

    mocked_options.clear()
    main_app.get_argument = ori_get_arg
    main_app.get_option = ori_get_opt


@contextlib.contextmanager
def init_parent():
    with tempfile.TemporaryDirectory() as temp_path:
        path = os_path_join(temp_path, DEF_PROJECT_PARENT_FOLDER)
        os.makedirs(path)
        yield path


def pdv_with_email(**pdv_kwargs) -> ProjectDevVars:
    """ pdv instance with non-empty values in AUTHOR and AUTHOR_EMAIL, to suppress pdv.errors() warnings. """
    pdv = ProjectDevVars(**pdv_kwargs)
    pdv['AUTHOR'] = 'AndiEcker'
    pdv['AUTHOR_EMAIL'] = 'aecker2@gmail.com'
    return pdv


@pytest.fixture
def temp_parent_path():
    with init_parent() as path:
        yield path


@contextlib.contextmanager
def _init_repo(pkg_name: str):
    with init_parent() as parent_path:
        project_path = os_path_join(parent_path, pkg_name)
        write_file(os_path_join(project_path, ".gitignore"), read_file(".gitignore"), make_dirs=True)
        with in_prj_dir_venv(project_path):
            # exit_on_err=False needed in all calls of sh_exit_if_exec_err() to prevent get_option call from _chk_if
            sh_exit_if_git_err(963, "git init", exit_on_err=False)
            sh_exit_if_git_err(963, "git config", extra_args=("user.email", "test@test.tst"), exit_on_err=False)
            sh_exit_if_git_err(963, "git config", extra_args=("user.name", "TestUserName"), exit_on_err=False)
            sh_exit_if_git_err(963, "git checkout", extra_args=("-b", DEF_MAIN_BRANCH))
            sh_exit_if_git_err(963, "git commit", extra_args=("-v", "--allow-empty", "-m", "unit tst repo init"))
        yield project_path


@pytest.fixture
def changed_repo_path():
    """ provide a git repository with uncommitted changes, yielding the project's temporary working tree root path. """
    with _init_repo(tst_ns_name + '_' + tst_ns_por_pfx + 'changed') as project_path:
        with in_prj_dir_venv(project_path):
            write_file(os_path_join(project_path, 'deleteD.x'), "--will be deleted")
            write_file(os_path_join(project_path, 'ChangeD.y'), "# will be changed")
            sh_exit_if_git_err(969, "git add", extra_args=["-A"], exit_on_err=False)
            sh_exit_if_git_err(969, "git commit", extra_args=["-m", "git commit message"], exit_on_err=False)

            write_file(os_path_join(project_path, 'addEd.ooo'), "# added/staged to repo")
            os.remove(os_path_join(project_path, 'deleteD.x'))
            write_file(os_path_join(project_path, 'ChangeD.y'), "# got changed")

        yield project_path


@pytest.fixture
def empty_repo_path():
    """ provide an empty git repository, yielding the path of the project's temporary working tree root. """
    with _init_repo(tst_ns_name + '_' + tst_ns_por_pfx + 'empty') as project_path:
        yield project_path


def ensure_tst_ns_portion_version_file(project_path: str) -> str:
    project_name = os_path_basename(project_path)
    if project_name.startswith(tst_ns_name + "_"):
        portion_suffix = project_name.rsplit('_', maxsplit=1)[-1]
        version_file_sub_path = os_path_join(tst_ns_name, tst_ns_por_pfx + portion_suffix + PY_EXT)
        version_file_path = os_path_join(project_path, version_file_sub_path)
        if not os_path_isfile(version_file_path):
            write_file(version_file_path,
                       f"\"\"\" {tst_ns_name} namespace {portion_suffix} tst portion \"\"\"{os.linesep}{os.linesep}"
                       f"__version__ = '{tst_pkg_version}'{os.linesep}",
                       make_dirs=True)
        return version_file_sub_path
    return ""


@pytest.fixture
def gitlab_remote():
    """ provide a connected Gitlab remote repository api """
    assert tst_mtn_token, f"missing/empty GitLab maintainer user account token in module variable {tst_mtn_token=}"
    remote_project = GitlabCom()
    remote_project.connect(pdv_with_email(**{'REPO_HOST_PROTOCOL': "https://",
                                             'repo_domain': TEST_PROJECTS_REMOTE,
                                             'repo_token': tst_mtn_token}))

    yield remote_project


@pytest.fixture
def module_repo_path():
    """ minimal/empty test namespace module project with lots of templates missing and one outdated. """
    with _init_repo(tst_ns_name + '_' + tst_ns_por_pfx + 'module') as project_path:
        ensure_tst_ns_portion_version_file(project_path)
        yield project_path


def remote_connect(pdv: ProjectDevVars, action: str) -> Union[GithubCom, GitlabCom]:
    host_api: Union[GithubCom, GitlabCom] = globals()[REGISTERED_HOSTS_CLASS_NAMES[TEST_PROJECTS_REMOTE]]()
    pdv['host_api'] = host_api  # pdv['host_api'] is needed by _check_action()
    assert host_api.connect(pdv), f" **** could not connect to remote host {TEST_PROJECTS_REMOTE} to {action} tst repo"
    return host_api


@pytest.fixture
def root_repo_path():
    """ minimal/empty test namespace root project. """
    with _init_repo(tst_root_prj_name) as project_path:
        with in_prj_dir_venv(project_path):
            write_file(os_path_join(tst_ns_name, tst_ns_name, PY_INIT),
                       f"\"\"\" {tst_ns_name} namespace root docstr \"\"\"{os.linesep}{os.linesep}"
                       f"__version__ = '333.69.96'{os.linesep}",
                       make_dirs=True)
        yield project_path


# helpers to find unwanted side effects on the environment
# def is_env_dirty() -> bool:
#     found = False
#     for var_name, var_val in os.environ.items():
#         if var_name.startswith(ENV_VAR_NAME_PREFIX):
#             print(f"¿¿¿¿¿¿{var_name} == {var_val!r}")
#             found = True
#         elif var_name.startswith('AE_OPTIONS_'):
#             print(f"¿¿¿¿¿¿{var_name} == {var_val!r}")
#             found = True
#
#     return found
#
# @pytest.fixture(autouse=True)
# def auto_use_fixture(request):
#     # if is_env_dirty():
#     #     print(f"=!=!=!BEG env polluted by test method {request.node.name}")
#     yield
#     if is_env_dirty():
#         print(f"=!=!=!END env polluted by test method {request.node.name}")


uncommitted_guess_prefix = f"¡detected main_branch='{DEF_MAIN_BRANCH}' with added/changed/uncommitted files"
