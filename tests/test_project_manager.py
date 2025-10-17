""" unit and integration tests for the aedev.project_manager.__main__ portion.

to run integration tests (~40 minutes), implemented in this test module:
* set the variable INTEGRATION_TESTS, declared at the top of this module, to True
* request a maintainer and contributor account in the test project group https://gitlab.com/aetst-group
* put the credentials of your GitLab maintainer account (itg_mtn_token) into your .env file(s)
* put the credentials of your GitLab contributor account (itg_ctb_token) into your .env file(s)
"""
import contextlib
import os
import shutil
import tempfile
import time

from collections import OrderedDict
from inspect import getframeinfo
from typing import Any, Iterable, Optional, Union
from unittest.mock import patch, MagicMock

import pytest

from conftest import skip_gitlab_ci
from packaging.version import Version

from ae.base import (
    BUILD_CONFIG_FILE, DEF_PROJECT_PARENT_FOLDER, DOCS_FOLDER, PY_EXT, PY_INIT, TEMPLATES_FOLDER, TESTS_FOLDER,
    in_wd, load_env_var_defaults, norm_name, norm_path, on_ci_host,
    os_path_basename, os_path_dirname, os_path_isdir, os_path_isfile, os_path_join,
    project_main_file, read_file, stack_frames, write_file, now_str)
# noinspection PyProtectedMember
from ae.core import _unregister_app_instance
from ae.paths import path_items
from ae.shell import (
    COMMIT_MSG_FILE_NAME, DEF_MAIN_BRANCH, EXEC_GIT_ERR_PREFIX, GIT_CLONE_CACHE_CONTEXT, GIT_RELEASE_REF_PREFIX,
    GIT_VERSION_TAG_PREFIX, PIP_INSTALL_CMD, PROJECT_VERSION_SEP, SHELL_LOG_FILE_NAME_SUFFIX,
    debug_or_verbose, get_main_app, get_pypi_versions, git_add, git_any, git_checkout, git_commit,
    git_current_branch, git_remotes, git_uncommitted,
    in_os_env, in_prj_dir_venv, sh_exit_if_git_err, sh_log, sh_logs, temp_context_cleanup)
from ae.dev_ops import (
    ANY_PRJ_TYPE, APP_PRJ, DJANGO_PRJ, ENV_VAR_NAME_PREFIX, MODULE_PRJ, NO_PRJ, PACKAGE_PRJ, PARENT_PRJ,
    PDV_NULL_VERSION, PDV_REPO_GROUP_SUFFIX, PDV_REQ_DEV_FILE_NAME, PLAYGROUND_PRJ, ROOT_PRJ,
    VERSION_PREFIX, VERSION_QUOTE,
    code_file_version, latest_remote_version, main_file_path, ProjectDevVars)
from ae.templates import (
    OUTSOURCED_FILE_NAME_PREFIX, OUTSOURCED_MARKER, CACHED_TPL_PROJECTS,
    TEMPLATE_INCLUDE_FILE_PLACEHOLDER_ID, TEMPLATE_PLACEHOLDER_ARGS_SUFFIX, TEMPLATE_PLACEHOLDER_ID_PREFIX,
    TEMPLATE_PLACEHOLDER_ID_SUFFIX, TPL_FILE_NAME_PREFIX, TPL_IMPORT_NAME_PREFIX, TPL_IMPORT_NAME_SUFFIX,
    register_template, template_path_option, template_version_option)

# noinspection PyProtectedMember
from aedev.project_manager.__main__ import (
    ARG_ALL, ARG_MULTIPLES, REGISTERED_ACTIONS, REGISTERED_HOSTS_CLASS_NAMES, TPL_IMPORT_NAMES,
    GithubCom, GitlabCom,
    _act_callable, _action, _available_actions, _expected_args,
    _get_app_option, _get_branch, _get_host_user_name, _get_host_user_token, _get_mirror_remote, _guess_next_action,
    _init_act_args_check, _init_act_exec_args, _init_children_pdv_args, _init_children_presets,
    _print_pdv, _refresh_templates, _renew_prj_dir, _renew_project, _show_status, _wait,
    add_children_file, cae, check_children_integrity, check_integrity, clone_children, clone_project, commit_children,
    commit_project, delete_children_file, increment_version, install_children_editable, install_editable,
    new_app, new_children, new_django, new_module, new_namespace_root, new_package, new_playground, renew_project,
    prepare_children_commit, prepare_commit, refresh_children_outsourced, rename_children_file, renew_children,
    run_children_command, show_actions, show_children_versions, update_mirror)


INTEGRATION_TESTS = False


def setup_module():
    """ clone template projects to speedup tests, printing warning messages if the tested module is not set up. """
    print()
    print(f"::::: {os_path_basename(__file__)} setup_module BEG - {get_main_app()=} {TEST_TPL_REGISTER=}")

    # for import_name in tst_namespaces_roots + TPL_IMPORT_NAMES:
    for import_name in TPL_IMPORT_NAMES:
        register_template(import_name, {}, CACHED_TPL_PROJECTS, (), [])

    write_file(norm_path(os_path_join("~", 'git' + SHELL_LOG_FILE_NAME_SUFFIX)),
               f"\n\n{now_str(sep='-')}\n# pjm test suite enabled global git log\n",
               extra_mode='a')

    # configure names/types/states/user-roles of all integration test projects (only runnable with maintainer user role)
    if INTEGRATION_TESTS and itg_ctb_token and itg_mtn_token and not on_ci_host():
        # 1st test prj has to be mtn-cloned ROOT_PRJ to allow update&push of new portion; auto-added to root/dev_req.txt
        itg_projects[itg_root_prj_name] = {'type': ROOT_PRJ, 'state': 'cloned', 'role': 'mtn'}
        itg_projects[f'{itg_ns_name}_{MODULE_PRJ}_forked_ctb_v'] = {'type': MODULE_PRJ, 'state': 'forked', 'role': 'ctb'
                                                                    }
        pkg_nam_prefix = f'{itg_ns_name}_{norm_name(PACKAGE_PRJ)}'
        itg_projects[f'{pkg_nam_prefix}_cloned_mtn_v'] = {'type': PACKAGE_PRJ, 'state': 'cloned', 'role': 'mtn'}
        itg_projects[f'{pkg_nam_prefix}_forked_mtn_v'] = {'type': PACKAGE_PRJ, 'state': 'forked', 'role': 'mtn'}
        itg_projects[f'{pkg_nam_prefix}_forked_ctb_v'] = {'type': PACKAGE_PRJ, 'state': 'forked', 'role': 'ctb'}
        for idx, prj_type in enumerate(_ for _ in ANY_PRJ_TYPE if _ != ROOT_PRJ):
            state = ('cloned', 'forked')[idx % 2]
            role = ('ctb', 'mtn')[int(idx / 2) % 2]
            prj_name = norm_name(prj_type) + "_" + state + "_" + role
            itg_projects[prj_name + "_v"] = {'type': prj_type, 'state': state, 'role': role}

        # setup of the initial|newly-adding integration test projects
        os.makedirs(itg_parent_path, exist_ok=True)
        portion_added = False
        for prj_name in itg_projects:
            portion_added = _prepare_itg_test_project(prj_name) and prj_name.startswith(itg_ns_name) or portion_added

        if portion_added:  # ensure portion added to ROOT_PRJ dev_requirements.txt will be pushed too
            if _uncommitted := git_uncommitted(itg_root_prj_path):
                if _uncommitted != {'dev_requirements.txt'}:
                    print(f"    # ignoring {_uncommitted=} mismatch in extended namespace root itg test project")
                root_pdv = ProjectDevVars(main_app_options={'branch': "pjm_itg_tst_portion_added_to_root_" + now_str(),
                                                            'delay': 3,  # needed by request_merge()/_get_app_option()
                                                            'versionIncrementPart': 3},  # .. by push/_get_app_option()
                                          project_path=itg_root_prj_path, repo_token=itg_mtn_token)
                root_pdv = _renew_project(root_pdv, ROOT_PRJ)
                _push_to_remote_and_pypi(root_pdv)
                print(f" !__! successfully pushed the auto-updated {_uncommitted} file(s) of {itg_root_prj_name}")

    # prevent call of ae.shell.exit_error() because it will unregister the main app instance cae and the template cache
    exit_error_patcher.append(patch('aedev.project_manager.__main__.exit_error', new=_log_exit_error_calls))
    exit_error_patcher.append(patch('ae.shell.exit_error', new=_log_exit_error_calls))
    for patcher in exit_error_patcher:
        patcher.start()

    print(f"::::: {os_path_basename(__file__)} setup_module END - {get_main_app()=} {TEST_TPL_REGISTER=}")


def teardown_module():
    """ check if the tested module is still set up correctly at the end of this test module. """
    print()
    print(f"::::: {os_path_basename(__file__)} teardown_module BEG - {get_main_app()=} {TEST_TPL_REGISTER=}")
    errors = []

    CACHED_TPL_PROJECTS.clear()  # prevent side effects if other module unit tests running after

    temp_context_cleanup(GIT_CLONE_CACHE_CONTEXT)  # remove temp cache of cloned tst_repo and template projects
    temp_context_cleanup()

    _unregister_app_instance(cae.app_key)  # remove registered main app from ae.core module/_APP_INSTANCES

    for err, msg, trace in logged_exit_error_calls:
        print(f" **** detected unpatched call of exit_error() with {err=} and {msg=}")
        for call_stack_entry in trace:
            print(f"    * {call_stack_entry}")
    for patcher in exit_error_patcher:
        patcher.stop()
    if logged_exit_error_calls:
        errors.append("detected unredirected calls of ae.shell.exit_error() in one or more unit tests")

    print(f"::::: {os_path_basename(__file__)} teardown_module END - {get_main_app()=} {TEST_TPL_REGISTER=}")

    assert not errors, f"test module teardown with {len(errors)} {errors=}"


# mock/replacement of :func:`as.shell.exit_error` to log calls when patched by func:`patched_exit_call_wrapper` fixture
exit_error_patcher = []
logged_exit_error_calls = []


def _log_exit_error_calls(error_code: int, error_message: str):
    """ ae.shell.exit_error()-mock to prevent unregister of main app and template projects and to log them in tests. """
    print()
    print(f"***** exit_error() called with {error_code=} and {error_message=}; stack:")
    trace = []
    for fra in stack_frames():
        inf = getframeinfo(fra)
        line = f"      File \"{inf.filename}\", line {inf.lineno}, in func={inf.function}: {inf.code_context}"
        print(line)     # print out stack trace line in the format so that PyCharm will create a link to the code line
        trace.append(line)
        if inf.function.startswith("test_"):
            break
    print()
    logged_exit_error_calls.append((error_code, error_message, trace))  # to be printed again by teardown_module()


# determine if the esc (external source code) parent folder exists on the local machine
esc_parent_path = _path if os_path_isdir(_path := os_path_join(os.getcwd(), "..", "..", 'esc')) else ""


# integration tests domain, local path, test projects, names|credentials for maintainer/mtn and contributor/ctb roles
itg_domain = 'gitlab.com'
itg_parent_path = norm_path(os_path_join('~', 'TsT'))
itg_ns_name = 'aetst'
itg_root_import_name = f'{itg_ns_name}.{itg_ns_name}'
itg_root_prj_name = f'{itg_ns_name}_{itg_ns_name}'
itg_root_prj_path = os_path_join(itg_parent_path, itg_root_prj_name)
itg_projects: dict[str, dict[str, str]] = {}  # 'type'=project_type 'state'='cloned'|'forked' 'role'='mtn'|'ctb'

# get contributor|ctb & maintainer|mtn credential/token (in env|config variables), needed to enable integration tests)
itg_ext_env = os.environ.copy()
load_env_var_defaults(".", itg_ext_env)  # use local machine pjm project user to get maintainer&contributor name/mail
itg_ctb_name = itg_ext_env.get('TEST_CONTRIBUTOR_NAME')
itg_ctb_token = itg_ext_env.get('TEST_CONTRIBUTOR_TOKEN')
# itg_ctb_email = itg_ext_env.get('TEST_CONTRIBUTOR_EMAIL')
itg_mtn_name = itg_ext_env.get(ENV_VAR_NAME_PREFIX + 'AUTHOR')
itg_mtn_token = itg_ext_env.get('AE_OPTIONS_REPO_TOKEN_AT_GITLAB_COM') if itg_mtn_name != itg_ctb_name else ""
# itg_mtn_email = itg_ext_env.get(ENV_VAR_NAME_PREFIX + 'AUTHOR_EMAIL')
# itg_ctb_root_url = f"https://oauth2:{itg_ctb_token}@{itg_domain}/{itg_ctb_name}"
# itg_mtn_root_url = f"https://oauth2:{itg_mtn_token}@{itg_domain}/{itg_ns_name}{PDV_REPO_GROUP_SUFFIX}"
skip_if_no_integration_tests = pytest.mark.skipif('not bool(itg_ctb_token) or not bool(itg_mtn_token)',
                                                  reason="contributor integration tests credentials are not available")
skip_if_not_maintainer = pytest.mark.skipif('not bool(itg_mtn_token)',
                                            reason=f"missing {itg_domain} maintainer personal-access-token")

# helpers for the initial setup of (initial or new) integration test projects


def _itg_pdv(project_name: str, branch: str = '', user_role: str = '') -> ProjectDevVars:
    role = user_role or itg_projects[project_name]['role']

    pdv_kwargs: dict[str, Any] = {'main_app_options': {'delay': 0.03, 'git_log': True, 'versionIncrementPart': 3},
                                  'project_path': os_path_join(itg_parent_path, project_name),
                                  'project_type': itg_projects[project_name]['type'],
                                  'AUTHOR': itg_mtn_name if role == 'mtn' else itg_ctb_name,
                                  'repo_user': itg_mtn_name if role == 'mtn' else itg_ctb_name,
                                  'repo_token': itg_mtn_token if role == 'mtn' else itg_ctb_token}

    if branch:
        pdv_kwargs['main_app_options']['branch'] = branch

    if project_name.startswith(itg_ns_name + "_"):
        pdv_kwargs['namespace_name'] = itg_ns_name
        pdv_kwargs['main_app_options'][template_path_option(itg_root_import_name)] = itg_root_prj_path
    elif role == 'ctb' and itg_projects[project_name]['state'] == 'cloned':
        pdv_kwargs['repo_group'] = itg_ctb_name
        pdv_kwargs['pip_name'] = ""
    else:
        pdv_kwargs['repo_group'] = itg_ns_name + PDV_REPO_GROUP_SUFFIX

    return ProjectDevVars(**pdv_kwargs)


def _prepare_itg_test_project(project_name: str) -> bool:
    """ prepare integration test project on local machine and on remote (if not exits). """
    project_path = os_path_join(itg_parent_path, project_name)
    prj_type = itg_projects[project_name]['type']
    prj_state = itg_projects[project_name]['state']
    prj_role = itg_projects[project_name]['role']
    ctb_project = prj_role == 'ctb' and prj_state == 'cloned'
    grp_name = itg_ctb_name if ctb_project else f"{itg_ns_name}{PDV_REPO_GROUP_SUFFIX}"
    remote_url = f"https://{itg_domain}/{grp_name}/{project_name}.git"

    add_remote = ((_out := git_any("..", 'ls-remote', remote_url)) and _out and _out[0].startswith(EXEC_GIT_ERR_PREFIX))

    if add_remote:  # newly added integration test project - create locally and push to remote
        if os_path_isdir(project_path):  # wipe any rests on local machine from cancelled new/added itg tst preparations
            shutil.rmtree(project_path)
        adding_role = 'ctb' if ctb_project else 'mtn'
        pdv = _itg_pdv(project_name, user_role=adding_role)
        _write_itg_env(project_name, user_role=adding_role)
        desc = f"preparing new {prj_type} project repository {project_name} for pjm integration tests"
        print(f" .!!. {desc} in {project_path=}, to be pushed onto {remote_url=} under the {adding_role=}")

        pdv.pdv_val('main_app_options')['branch'] = f"{norm_name(desc)}_on_{now_str(sep='_')}"
        pdv = _renew_project(pdv, prj_type)
        pdv.pdv_val('main_app_options').pop('branch')
        _push_to_remote_and_pypi(pdv)
        shutil.rmtree(project_path)

    if prj_state == 'cloned' and os_path_isdir(project_path):
        shutil.rmtree(project_path)
    pdv = _itg_pdv(project_name)
    if prj_state == 'cloned':
        clone_project(pdv, project_name)
    else:
        pdv['host_api'] = host_api = _remote_connect(pdv, "fork")
        host_api.fork_project(pdv, itg_ns_name + PDV_REPO_GROUP_SUFFIX + '/' + project_name)
    _write_itg_env(project_name)

    print(f" !!!! prepared {pdv['project_desc']} in {project_path=}" + (f" and at {remote_url=}" if add_remote else ""))

    return add_remote


def _push_to_remote_and_pypi(pdv: ProjectDevVars):
    project_path, project_name = pdv['project_path'], pdv['project_name']

    git_add(project_path)
    prepare_commit(pdv, f"{project_name} created/extended by integration test preparation. V {{project_version}}")
    commit_project(pdv)

    pdv['host_api'] = host_api = _remote_connect(pdv, "push-new-itg-project")
    host_api.push_project(pdv)
    host_api.request_merge(pdv)
    host_api.release_project(pdv, 'LATEST')

    if pdv['pip_name']:
        retries = 69  # waiting/checking/retrying maximal ~= 6 minutes (test.pypi.org is slow)
        while retries and get_pypi_versions(pdv['pip_name'], pypi_test=True)[-1] != pdv['project_version']:
            print(f"  ... waiting for the test.pypi.org release of the added {project_name} test project; {retries=}")
            time.sleep(6)
            retries -= 1

    print(f"  ^^  {project_path} committed and pushed to origin{' and PyPI' if pdv['pip_name'] else ''}")


def _remote_connect(pdv: ProjectDevVars, action: str) -> Union[GithubCom, GitlabCom]:
    host_api: Union[GithubCom, GitlabCom] = globals()[REGISTERED_HOSTS_CLASS_NAMES[itg_domain]]()
    pdv['host_api'] = host_api  # pdv['host_api'] is needed by _check_action()
    assert host_api.connect(pdv), f" **** could not connect to remote host {itg_domain} to {action} itg repo"
    return host_api


def _write_itg_env(project_name: str, user_role: str = ''):
    prj_path = os_path_join(itg_parent_path, project_name)
    prj_role = itg_projects[project_name]['role']
    is_maintainer = (user_role or prj_role) == 'mtn'

    var_names_values = (
        (ENV_VAR_NAME_PREFIX + 'AUTHOR', itg_mtn_name if is_maintainer else itg_ctb_name),
        # (ENV_VAR_NAME_PREFIX + 'AUTHOR_EMAIL', itg_mtn_email if is_mtn else itg_ctb_email),
        (ENV_VAR_NAME_PREFIX + 'repo_user', itg_mtn_name if is_maintainer else itg_ctb_name),
        (ENV_VAR_NAME_PREFIX + 'repo_token', itg_mtn_token if is_maintainer else itg_ctb_token),
    )
    if prj_role == 'ctb' and itg_projects[project_name]['state'] == 'cloned':
        var_names_values += ((ENV_VAR_NAME_PREFIX + 'repo_group', itg_ctb_name),
                             (ENV_VAR_NAME_PREFIX + 'pip_name', '""'))
    elif not project_name.startswith(itg_ns_name + "_"):  # is namespace root/portion project
        var_names_values += ((ENV_VAR_NAME_PREFIX + 'repo_group', f'{itg_ns_name}{PDV_REPO_GROUP_SUFFIX}'), )

    write_file(os_path_join(prj_path, '.env'),
               f"# auto-generated for {prj_role} user by pjm-test_project_manager integration tests" + os.linesep +
               os.linesep.join(nam + "=" + val for nam, val in var_names_values) + os.linesep,
               make_dirs=True)

    sh_log(f"# {project_name=} integration test enabled/extended git log; user role: {user_role or prj_role}",
           log_file_paths=sh_logs(log_enable_dir=prj_path, log_name_prefix='git'))


def paths_of_test_projects(*local_paths: str, filter_state: str = '', filter_role: str = '') -> Iterable[str]:
    remote_paths = [os_path_join(itg_parent_path, _prj_name) for _prj_name, _info in itg_projects.items()
                    if (filter_state == '' or _info['state'] == filter_state)
                    and (filter_role == '' or _info['role'] == filter_role)]

    return *local_paths, *remote_paths


# ---prepare unfinished/empty/changed namespace module/portion names&versions for unit tests (only on the local machine)

tst_ns_name = 'nsn'
tst_ns_por_pfx = 'tst_por_'                 # portion name prefix for changed_repo_path/empty_repo_path/module_repo_path
tst_imp_pfx = tst_ns_name + '.' + tst_ns_por_pfx
tst_pkg_pfx = tst_ns_name + '_' + tst_ns_por_pfx
tst_pkg_version = increment_version(PDV_NULL_VERSION)
tst_nxt_pgk_ver = increment_version(tst_pkg_version)

tst_root_prj_name = tst_ns_name + '_' + tst_ns_name
tst_namespaces_roots = [tst_ns_name + '.' + tst_ns_name]
if itg_ctb_token:
    tst_namespaces_roots.append(itg_root_import_name)
TEST_TPL_REGISTER = {}      # map of the 3 template registers used by the tests, initialized in setup_module()


@pytest.fixture
def mocked_app_options():
    """ mock ConsoleApp option/config-var-setter/getter and option value requests via _get_app_option/debug_or_verbose.

    main ConsoleApp instance argument parsing gets prevented by monkey-patching, e.g., of main_app.get_option().
    direct access to pdv['main_app_options'] gets not detected and mocked by this fixture; useful to fix side effects
    of mocked child-pdv when option values should only be specified for the parent.

    because cae is only initialized but no args got parsed. therefore and to let debug_or_verbose() also behave like the
    value specified by the mocked option 'more_verbose', ae.shell.debug_or_verbose() will also get patched accordingly.
    """
    def _app_option(_pdv: ProjectDevVars, opt_nam: str) -> Optional[Any]:
        if opt_nam in mocked_options:
            return mocked_options[opt_nam]
        return _get_app_option(_pdv, opt_nam)

    def _dbg_or_verbose():
        return mocked_options.get('more_verbose', False)

    main_app = get_main_app()
    ori_get_arg = main_app.get_argument
    ori_get_opt = main_app.get_option

    mocked_options: dict[str, Any] = {}
    mocked_options.update({template_path_option(import_name): ""
                           for import_name in tst_namespaces_roots + TPL_IMPORT_NAMES})
    mocked_options.update({template_version_option(import_name): ""
                           for import_name in tst_namespaces_roots + TPL_IMPORT_NAMES})

    main_app.get_argument = main_app.get_option = lambda opt: mocked_options.get(opt, None)

    with (patch('aedev.project_manager.__main__._get_app_option', new=_app_option),
          patch('ae.dev_ops.get_main_app', return_value=main_app),
          patch('ae.shell.get_main_app', return_value=main_app),
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


@pytest.fixture
def gitlab_remote():
    """ provide a connected Gitlab remote repository api. """
    remote_project = GitlabCom()
    remote_project.connect(ProjectDevVars(**{'REPO_HOST_PROTOCOL': "https://",
                                             'repo_domain': itg_domain,
                                             'repo_token': itg_mtn_token}))

    yield remote_project


def _ensure_tst_ns_portion_version_file(project_path: str) -> str:
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
def module_repo_path():
    """ minimal/empty test namespace module project. """
    with _init_repo(tst_ns_name + '_' + tst_ns_por_pfx + 'module') as project_path:
        _ensure_tst_ns_portion_version_file(project_path)
        yield project_path


@pytest.fixture
def patched_exit_call_wrapper(mocked_app_options):
    """ log :func:`ae.shell.exit_error` function calls and args, while preventing main app shutdown.

    inherit from mocked_app_options to prevent call of get_option()/parse_arguments() from check_if()
    """
    exit_call_args = []

    class _ExitCaller(Exception):
        """ exception to recognize and simulate app exit for function to be tested. """

    def _exit_(*args, **kwargs):
        # nonlocal exit_call_args
        exit_call_args.append((args, kwargs))
        raise _ExitCaller("to be caught by the _call_wrapper() of the patched_exit_call_wrapper unit test fixture")

    def _call_wrapper(fun, *args, **kwargs):
        exit_call_args.clear()
        try:
            ret = fun(*args, **kwargs)
        except _ExitCaller:
            ret = None
        print(f"patched_exit_call_wrapper._call_wrapper {ret=}")
        return exit_call_args

    with patch('aedev.project_manager.__main__.exit_error', new=_exit_), patch('ae.shell.exit_error', new=_exit_):
        yield _call_wrapper


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


def test_setup_of_test_constants_and_projects(changed_repo_path, empty_repo_path, module_repo_path):
    assert REGISTERED_ACTIONS
    assert REGISTERED_HOSTS_CLASS_NAMES
    assert TPL_IMPORT_NAMES
    assert CACHED_TPL_PROJECTS

    assert not os_path_isfile(os_path_join(itg_parent_path, '.env'))  # ensure gap to prevent bleeding credentials/.envs

    parent_without_git_folder = os_path_dirname(empty_repo_path)
    for prj_path in (parent_without_git_folder, changed_repo_path, empty_repo_path, module_repo_path):
        pdv = ProjectDevVars(project_path=prj_path)
        assert latest_remote_version(pdv) == "0.3.1", f"failed for {prj_path=}"

        prj_state = _guess_next_action(pdv)
        if prj_path == parent_without_git_folder:
            assert prj_state.startswith("¡no git repository found"), f"failed for {prj_path=}"
        elif prj_path in (changed_repo_path, empty_repo_path):
            assert prj_state.startswith("¡empty or invalid project version"), f"failed for {prj_path=}"
        else:
            assert prj_state.startswith(uncommitted_guess_prefix), f"failed for {prj_path=}"

    for prj_path in paths_of_test_projects():
        pdv = ProjectDevVars(project_path=prj_path)

        assert Version(latest_remote_version(pdv)) > Version(pdv['NULL_VERSION']), f"failed for {prj_path=}"
        assert Version(latest_remote_version(pdv, increment_part=0)) == Version(pdv['project_version']), f"{prj_path=}"

        assert _guess_next_action(pdv) == 'renew_project', f"failed for {prj_path=}"

    print("``````test setup checks finished")


@skip_gitlab_ci  # skip on gitlab because of a missing remote repository user account token
class TestActionsGitLab:
    def test_clean_releases(self, gitlab_remote, mocked_app_options, module_repo_path):
        mocked_app_options['project_path'] = module_repo_path
        mocked_app_options['repo_token'] = itg_mtn_token
        mocked_app_options['more_verbose'] = True

        gitlab_remote.clean_releases(ProjectDevVars(project_path=module_repo_path))

    def test_fork_project(self, gitlab_remote, temp_parent_path):
        project_name = 'ae_base'
        project_path = os_path_join(esc_parent_path or temp_parent_path, project_name)
        pdv = ProjectDevVars(project_path=project_path)

        gitlab_remote.fork_project(pdv, "ae-group/" + project_name)

        assert os_path_isdir(project_path)
        assert os_path_isfile(os_path_join(project_path, 'ae', 'base.py'))
        assert pdv['REMOTE_UPSTREAM'] in git_remotes(project_path)

    def test_show_remote(self, capsys, gitlab_remote):
        with (patch('aedev.project_manager.__main__._get_host_group', return_value="ae-group"),
              patch('aedev.project_manager.__main__._get_host_domain', return_value=""),
              ):
            gitlab_remote.show_remote(ProjectDevVars(project_path=".."), "ae-group/ae_base")
            output = capsys.readouterr().out
            assert "default_branch = develop" in output
            assert "path_with_namespace = ae-group/ae_base" in output
            assert "visibility = public" in output

    def test_show_children_status(self, capsys, changed_repo_path, empty_repo_path, gitlab_remote, mocked_app_options,
                                  module_repo_path):
        mocked_app_options['more_verbose'] = False
        chi_prj_vars = {norm_name(os_path_basename(_)): ProjectDevVars(project_path=_) 
                        for _ in (changed_repo_path, empty_repo_path, module_repo_path)}
        par_pdv = ProjectDevVars(project_path=os_path_dirname(changed_repo_path), project_type=PARENT_PRJ,
                                 children_project_vars=chi_prj_vars)
        assert par_pdv['project_type'] == PARENT_PRJ

        gitlab_remote.show_children_status(par_pdv, *(chi_prj_vars.values()))

        output = capsys.readouterr().out
        assert "-- project vars:" not in output
        assert "-- git status:" not in output
        assert "*** next action discrepancy:" in output

        mocked_app_options['more_verbose'] = True

        gitlab_remote.show_children_status(par_pdv, *(chi_prj_vars.values()))

        output = capsys.readouterr().out
        assert output
        assert "-- project vars:" in output
        assert "-- git status:" in output
        assert "*** next action discrepancy:" in output

    def test_show_status(self, capsys, changed_repo_path, empty_repo_path, gitlab_remote, module_repo_path):
        verbose = debug_or_verbose()
        err_prefix = "empty or invalid project version"
        for project_path in paths_of_test_projects(changed_repo_path, empty_repo_path, module_repo_path):

            gitlab_remote.show_status(ProjectDevVars(project_path=project_path))

            output = capsys.readouterr().out
            assert ("-- project vars:" in output) is verbose
            assert ("-- git status:" in output) is verbose
            if project_path in (changed_repo_path, empty_repo_path):
                assert "*** next action discrepancy:" in output, f"with {project_path=}"
                assert err_prefix in output, f"with {project_path=}"
            elif project_path == module_repo_path:
                assert "*** next action discrepancy:" in output, f"with {project_path=}"
                assert ("detected main_branch='develop' with added/changed/uncommitted files: ?? .gitignore, ?? " +
                        tst_ns_name + "/" + tst_ns_por_pfx + 'module' + PY_EXT) in output, f"with {project_path=}"
            else:
                assert "-- next action guess: renew_project" in output, f"with {project_path=}"

    def test_show_status_main_branch(self, capsys, changed_repo_path, empty_repo_path, gitlab_remote, module_repo_path):
        verbose = debug_or_verbose()
        err_prefix = "detected main_branch='develop' with added/changed/uncommitted files: "
        for project_path in paths_of_test_projects(changed_repo_path, empty_repo_path, module_repo_path):
            _ensure_tst_ns_portion_version_file(project_path)  # needed for changed/empty, leave itg projects untouched

            gitlab_remote.show_status(ProjectDevVars(project_path=project_path))

            output = capsys.readouterr().out
            assert ("-- project vars:" in output) is verbose
            assert ("-- git status:" in output) is verbose
            if project_path == changed_repo_path:
                assert "*** next action discrepancy:" in output, f"with {project_path=}"
                assert err_prefix + " M " + 'ChangeD.y' + ",  D " + 'deleteD.x' + ", ?? " + 'addEd.ooo' in output
            elif project_path == empty_repo_path:
                assert "*** next action discrepancy:" in output, f"with {project_path=}"
                assert err_prefix + "?? .gitignore" in output, f"with {project_path=}"
            elif project_path == module_repo_path:
                assert "*** next action discrepancy:" in output, f"with {project_path=}"
                assert err_prefix + "?? .gitignore, ?? nsn/" + tst_ns_por_pfx + 'module' + PY_EXT in output
            else:  # itg tst projects
                assert "-- next action guess: renew_project" in output

    def test_show_status_unstaged(self, capsys, changed_repo_path, empty_repo_path, gitlab_remote, module_repo_path):
        verbose = debug_or_verbose()
        err_prefix = "unstaged files found! run git add, or delete them: "
        for project_path in (changed_repo_path, empty_repo_path, module_repo_path):
            _ensure_tst_ns_portion_version_file(project_path)
            assert git_checkout(project_path, new_branch="feature_branch_to_prevent_check_action_errors") == ""
            pdv = ProjectDevVars(project_path=project_path)

            gitlab_remote.show_status(pdv)

            output = capsys.readouterr().out
            assert ("-- project vars:" in output) is verbose
            assert ("-- git status:" in output) is verbose
            if project_path == changed_repo_path:
                assert "*** next action discrepancy:" in output, f"with {project_path=}"
                assert err_prefix + " M " + 'ChangeD.y' + ",  D " + 'deleteD.x' + ", ?? " + 'addEd.ooo' in output
            elif project_path == empty_repo_path:
                assert "*** next action discrepancy:" in output, f"with {project_path=}"
                assert err_prefix + "?? .gitignore" in output, f"with {project_path=}"
            elif project_path == module_repo_path:
                assert "*** next action discrepancy:" in output, f"with {project_path=}"
                assert err_prefix + "?? .gitignore, ?? nsn/" + tst_ns_por_pfx + 'module' + PY_EXT in output
            else:
                assert False, "itg test projects does not make sense here"

    def test_show_status_committed(self, capsys, changed_repo_path, empty_repo_path, gitlab_remote, module_repo_path):
        verbose = debug_or_verbose()
        for project_path in (changed_repo_path, empty_repo_path, module_repo_path):
            _ensure_tst_ns_portion_version_file(project_path)
            git_checkout(project_path, new_branch="feature_branch_to_prevent_check_action_errors")
            git_add(project_path)
            pdv = ProjectDevVars(project_path=project_path)
            if project_path in (changed_repo_path, empty_repo_path, module_repo_path):
                prepare_commit(pdv, f"commit of {project_path=} for show-status action tests V {{project_version}}")
                commit_project(pdv)

            gitlab_remote.show_status(pdv)

            output = capsys.readouterr().out
            assert "-- next action guess: push_project" in output, f"with {project_path=}"
            assert ("-- project vars:" in output) is verbose, f"with {project_path=}"
            assert ("-- git status:" in output) is verbose, f"with {project_path=}"


class TestActionsLocal:
    def test_add_children_file(self, empty_repo_path, mocked_app_options, module_repo_path):
        mocked_app_options['project_path'] = module_repo_path
        mocked_app_options['more_verbose'] = True

        file_name = "add_tst_file.abc"
        file_content = "file content"
        file_src_path = os_path_join(module_repo_path, file_name)
        write_file(file_src_path, file_content)
        file_dst_path = os_path_join(module_repo_path, tst_ns_name, file_name)
        tpl_name = OUTSOURCED_FILE_NAME_PREFIX + "add_tpl_file.xyz"
        tpl_content = "tpl content"
        tpl_src_path = os_path_join(module_repo_path, tpl_name)
        write_file(tpl_src_path, tpl_content)
        tpl_dst_path = os_path_join(module_repo_path, tst_ns_name, tpl_name[len(OUTSOURCED_FILE_NAME_PREFIX):])
        mod_pdv = ProjectDevVars(project_path=module_repo_path)

        assert not add_children_file(mod_pdv, "not_existing_file.xxx", tst_ns_name, mod_pdv)

        new_pdv = ProjectDevVars(project_path=empty_repo_path)
        new_dst_path = os_path_join(empty_repo_path, tst_ns_name, file_name)
        assert not add_children_file(new_pdv, file_src_path, tst_ns_name, new_pdv)  # fail because no tst_ns_name dir

        os.makedirs(os_path_join(empty_repo_path, tst_ns_name))
        assert not os_path_isfile(new_dst_path)
        mod_pdv['project_type'] = ROOT_PRJ
        assert add_children_file(mod_pdv, file_src_path, tst_ns_name, new_pdv)
        assert os_path_isfile(file_dst_path)
        assert file_content == read_file(file_dst_path)
        assert os_path_isfile(new_dst_path)
        assert file_content == read_file(new_dst_path)

        os.remove(file_dst_path)

        assert not os_path_isfile(file_dst_path)
        assert not add_children_file(mod_pdv, file_src_path, tst_ns_name, mod_pdv)  # False: added to parent and child
        assert os_path_isfile(file_dst_path)
        assert file_content == read_file(file_dst_path)

        assert not os_path_isfile(tpl_dst_path)

        assert not add_children_file(mod_pdv, tpl_src_path, tst_ns_name, mod_pdv)

        assert os_path_isfile(tpl_dst_path)
        assert tpl_content in read_file(tpl_dst_path)
        assert OUTSOURCED_MARKER in read_file(tpl_dst_path)

    def test_check_children_integrity(self, capsys, changed_repo_path, empty_repo_path, module_repo_path):
        par_pdv = ProjectDevVars(project_path=os_path_dirname(changed_repo_path))

        check_children_integrity(par_pdv, ProjectDevVars(project_path=changed_repo_path))
        assert " ==== " in capsys.readouterr().out

        check_children_integrity(par_pdv, ProjectDevVars(project_path=empty_repo_path))
        assert " ==== " in capsys.readouterr().out

        # removed together with patched_exit_call_wrapper arg because fails with error '(46, ')
        # .. but only when running on console via pjm command line (not in PyCharm)
        # cl=patched_exit_call_wrapper(check_children_integrity, par_pdv, ProjectDevVars(project_path=module_repo_path))
        # assert len(cl) == 1
        # assert cl[0][0][0] == 44    # '(44, '
        # assert capsys.readouterr().out

    def test_check_integrity(self, capsys, changed_repo_path, empty_repo_path):
        check_integrity(ProjectDevVars(project_path=changed_repo_path))
        assert capsys.readouterr().out

        check_integrity(ProjectDevVars(project_path=empty_repo_path))
        assert capsys.readouterr().out

    def test_check_integrity_errors(self, capsys, mocked_app_options, module_repo_path, patched_exit_call_wrapper):
        mocked_app_options['more_verbose'] = False

        calls = patched_exit_call_wrapper(check_integrity, ProjectDevVars(project_path=module_repo_path))

        assert len(calls) == 1
        assert capsys.readouterr().out

        mocked_app_options['more_verbose'] = True

        calls = patched_exit_call_wrapper(check_integrity, ProjectDevVars(project_path=module_repo_path))

        assert len(calls) == 1
        assert capsys.readouterr().out

    def test_clone_children_of_ae_namespace(self):
        project_versions = (f"ae-group/ae_base{PROJECT_VERSION_SEP}0.3.60", f"ae_paths{PROJECT_VERSION_SEP}0.3.42")

        with init_parent() as parent_dir:
            par_pdv = ProjectDevVars(project_path=parent_dir, namespace_name='ae', repo_group='ae-group')

            project_paths = clone_children(par_pdv, *project_versions)

            for idx, project_path in enumerate(project_paths):
                assert project_path.startswith(parent_dir)
                assert os_path_isdir(project_path)
                import_name = '.'.join(os_path_basename(project_path).split('_', maxsplit=1))
                version = project_versions[idx].split(PROJECT_VERSION_SEP)[1]
                assert version == code_file_version(project_main_file(import_name, project_path=project_path))

    def test_clone_project_via_app_options_and_release_branch(self):
        import_name = 'ae.console'
        project_name = norm_name(import_name)
        project_version = "0.3.81"

        with init_parent() as parent_dir:
            par_pdv = ProjectDevVars(main_app_options={'branch': GIT_RELEASE_REF_PREFIX + project_version},
                                     project_path=parent_dir, repo_group='ae-group')

            project_path = clone_project(par_pdv, project_name)

            assert project_path.startswith(parent_dir)
            assert project_path == os_path_join(parent_dir, project_name)
            assert os_path_isdir(project_path)
            assert project_version == code_file_version(project_main_file(import_name, project_path=project_path))

    def test_clone_project_via_app_options_and_version_tag(self):
        import_name = 'ae.console'
        project_name = norm_name(import_name)
        project_version = "0.3.81"

        with init_parent() as parent_dir:
            par_pdv = ProjectDevVars(main_app_options={'branch': GIT_VERSION_TAG_PREFIX + project_version},
                                     project_path=parent_dir, repo_group='ae-group')

            project_path = clone_project(par_pdv, project_name)

            assert project_path.startswith(parent_dir)
            assert project_path == os_path_join(parent_dir, project_name)
            assert os_path_isdir(project_path)
            assert project_version == code_file_version(project_main_file(import_name, project_path=project_path))

    def test_clone_project_via_owner_name_prefix(self):
        group_name = 'ae-group'
        import_name = 'ae.base'
        project_name = norm_name(import_name)
        project_version = "0.3.63"

        with init_parent() as par_dir:

            project_path = clone_project(ProjectDevVars(project_path=par_dir),
                                         group_name + "/" + project_name + PROJECT_VERSION_SEP + project_version)

            assert project_path
            assert project_path.startswith(par_dir)
            assert project_path == os_path_join(par_dir, project_name)
            assert os_path_isdir(project_path)
            assert project_version == code_file_version(project_main_file(import_name, project_path=project_path))

    def test_commit_children(self, mocked_app_options, module_repo_path, patched_exit_call_wrapper):
        mocked_app_options['project_path'] = os_path_dirname(module_repo_path)
        mocked_app_options['more_verbose'] = True
        write_file(os_path_join(module_repo_path, COMMIT_MSG_FILE_NAME), "commit message testing commit_children")

        cl = patched_exit_call_wrapper(commit_children,
                                       ProjectDevVars(project_path=os_path_dirname(module_repo_path)),
                                       ProjectDevVars(project_path=module_repo_path))
        assert len(cl) == 1         # _check_action() failed because of no-branch/unstaged files/commit-msg-file-w/o-ver
        assert cl[0][0][0] == 13    # '(13, '

        git_checkout(module_repo_path, new_branch="new_branch_for_test_commit_children")
        git_add(module_repo_path)
        write_file(os_path_join(module_repo_path, COMMIT_MSG_FILE_NAME), "children with {project_version} placeholder")

        commit_children(ProjectDevVars(project_path=os_path_dirname(module_repo_path)),
                        ProjectDevVars(project_path=module_repo_path))

    def test_commit_project(self, mocked_app_options, module_repo_path, patched_exit_call_wrapper):
        mocked_app_options['more_verbose'] = True
        write_file(os_path_join(module_repo_path, COMMIT_MSG_FILE_NAME), "commit project msg w/o version placeholder")

        assert patched_exit_call_wrapper(commit_project, ProjectDevVars(project_path=module_repo_path))

        git_add(module_repo_path)

        assert patched_exit_call_wrapper(commit_project, ProjectDevVars(project_path=module_repo_path))

        git_checkout(module_repo_path, new_branch="tst_commit_project_branch_name")

        assert patched_exit_call_wrapper(commit_project, ProjectDevVars(project_path=module_repo_path))

        write_file(os_path_join(module_repo_path, COMMIT_MSG_FILE_NAME), "msg-title with {project_version} placeholder")

        assert not patched_exit_call_wrapper(commit_project, ProjectDevVars(project_path=module_repo_path))

    def test_delete_children_file(self, empty_repo_path, mocked_app_options, module_repo_path):
        mocked_app_options['project_path'] = module_repo_path
        mocked_app_options['more_verbose'] = True
        root_pdv = ProjectDevVars(project_path=empty_repo_path)
        root_pdv['project_type'] = ROOT_PRJ
        mod_pdv = ProjectDevVars(project_path=module_repo_path)

        del_dir = "del_dir"
        os.makedirs(os_path_join(empty_repo_path, del_dir))
        assert os_path_isdir(os_path_join(empty_repo_path, del_dir))
        os.makedirs(os_path_join(module_repo_path, del_dir))
        assert os_path_isdir(os_path_join(module_repo_path, del_dir))
        assert delete_children_file(root_pdv, del_dir, mod_pdv)
        assert not os_path_isdir(os_path_join(empty_repo_path, del_dir))
        assert not os_path_isdir(os_path_join(module_repo_path, del_dir))

        del_file = os_path_join(module_repo_path, tst_ns_name, tst_ns_por_pfx + 'module' + PY_EXT)
        assert os_path_isfile(del_file)
        assert not delete_children_file(root_pdv, del_file, mod_pdv)
        assert not os_path_isfile(del_file)

    def test_install_children_editable(self, module_repo_path):
        call_mock = MagicMock()
        with patch('aedev.project_manager.__main__.sh_exit_if_exec_err', new=call_mock):
            install_children_editable(ProjectDevVars(project_path=os_path_dirname(module_repo_path)),
                                      ProjectDevVars(project_path=module_repo_path))
        assert call_mock.call_count == 1
        args = call_mock.call_args.args
        assert args[0] == 90
        assert args[1].startswith(PIP_INSTALL_CMD)

    def test_install_editable(self, module_repo_path):
        call_mock = MagicMock()
        with patch('aedev.project_manager.__main__.sh_exit_if_exec_err', new=call_mock):
            install_editable(ProjectDevVars(project_path=module_repo_path))
        assert call_mock.call_count == 1
        args = call_mock.call_args.args
        assert args[0] == 90
        assert args[1].startswith(PIP_INSTALL_CMD)

    def test_new_app(self):
        with init_parent() as par_path:
            project_name = "TstApp"
            project_path = os_path_join(par_path, project_name)
            pdv = ProjectDevVars(main_app_options={'project_path': project_path}, project_path=project_path)

            pdv = new_app(pdv)

            assert pdv['project_type'] == APP_PRJ
            assert not os_path_isfile(main_file_path(project_path, MODULE_PRJ))
            main_file = main_file_path(project_path, APP_PRJ)
            assert os_path_isfile(main_file)
            assert code_file_version(main_file) == pdv['NULL_VERSION']  # no main_app_options['versionIncrementPart']

    def test_new_children(self, mocked_app_options, module_repo_path):
        mocked_app_options['namespace_name'] = tst_ns_name

        parent_pdv = ProjectDevVars(project_path=os_path_dirname(module_repo_path), 
                                    main_app_options=mocked_app_options.copy(), **mocked_app_options)
        module_pdv = ProjectDevVars(project_path=module_repo_path,
                                    main_app_options=mocked_app_options.copy(), **mocked_app_options)
        assert os_path_isfile(main_file_path(module_repo_path, MODULE_PRJ, namespace_name=tst_ns_name))
        assert not os_path_isfile(main_file_path(module_repo_path, PACKAGE_PRJ, namespace_name=tst_ns_name))

        new_pdvs = new_children(parent_pdv, module_pdv)
        
        assert len(new_pdvs) == 1
        assert new_pdvs[0]['project_type'] == MODULE_PRJ
        assert os_path_isfile(main_file_path(module_repo_path, MODULE_PRJ, namespace_name=tst_ns_name))
        assert not os_path_isfile(main_file_path(module_repo_path, PACKAGE_PRJ, namespace_name=tst_ns_name))

    def test_new_django(self, temp_parent_path):
        project_path = os_path_join(temp_parent_path, "django_project_root")
        pdv = ProjectDevVars(main_app_options=project_path, project_path=project_path)

        new_pdv = new_django(pdv)

        assert new_pdv['project_type'] == DJANGO_PRJ
        assert os_path_isfile(main_file_path(project_path, DJANGO_PRJ))

    def test_new_django_without_namespace(self, mocked_app_options, empty_repo_path):
        mocked_app_options['project_path'] = empty_repo_path

        pdv = ProjectDevVars(project_path=empty_repo_path)
        assert pdv['project_type'] == NO_PRJ
        assert not os_path_isfile(main_file_path(empty_repo_path, DJANGO_PRJ))

        new_pdv = new_django(pdv)

        assert new_pdv['project_type'] == DJANGO_PRJ
        assert os_path_isfile(main_file_path(empty_repo_path, DJANGO_PRJ))

    def test_new_module(self, mocked_app_options, module_repo_path):
        mocked_app_options['namespace_name'] = tst_ns_name
        mocked_app_options['project_path'] = module_repo_path

        pdv = ProjectDevVars(project_path=module_repo_path)
        assert os_path_isfile(main_file_path(module_repo_path, MODULE_PRJ, namespace_name=tst_ns_name))
        assert not os_path_isfile(main_file_path(module_repo_path, PACKAGE_PRJ, namespace_name=tst_ns_name))

        new_pdv = new_module(pdv)
        assert new_pdv['project_type'] == MODULE_PRJ
        assert os_path_isfile(main_file_path(module_repo_path, MODULE_PRJ, namespace_name=tst_ns_name))
        assert not os_path_isfile(main_file_path(module_repo_path, PACKAGE_PRJ, namespace_name=tst_ns_name))

    def test_new_module_from_root(self, mocked_app_options, root_repo_path):
        mocked_app_options['namespace_name'] = tst_ns_name
        mocked_app_options['project_path'] = root_repo_path

        pdv = ProjectDevVars(main_app_options=mocked_app_options.copy(), **mocked_app_options)
        assert not os_path_isfile(main_file_path(root_repo_path, MODULE_PRJ, namespace_name=tst_ns_name))
        assert os_path_isfile(main_file_path(root_repo_path, ROOT_PRJ, namespace_name=tst_ns_name))

        new_pdv = new_namespace_root(pdv)
        assert new_pdv['project_type'] == ROOT_PRJ
        assert not os_path_isfile(main_file_path(root_repo_path, MODULE_PRJ, namespace_name=tst_ns_name))
        assert os_path_isfile(main_file_path(root_repo_path, ROOT_PRJ, namespace_name=tst_ns_name))
        assert os_path_isfile(main_file_path(new_pdv['project_path'], ROOT_PRJ, namespace_name=tst_ns_name))

    def test_new_namespace_root(self, temp_parent_path):
        project_path = os_path_join(temp_parent_path, tst_root_prj_name)
        pdv = ProjectDevVars(main_app_options={'versionIncrementPart': 3},
                             namespace_name=tst_ns_name, project_path=project_path)

        new_pdv = new_namespace_root(pdv)

        assert new_pdv['project_type'] == ROOT_PRJ
        assert os_path_isdir(project_path)
        ver_file_path = main_file_path(project_path, ROOT_PRJ, namespace_name=tst_ns_name)
        assert os_path_isfile(ver_file_path)
        assert os_path_basename(ver_file_path) == PY_INIT
        assert code_file_version(ver_file_path) == "0.3.1"

    def test_new_package(self, temp_parent_path):
        tst_prj = 'tst_prj_name'
        prj_path = os_path_join(temp_parent_path, tst_prj)

        new_pdv = new_package(ProjectDevVars(project_path=prj_path))

        assert new_pdv['project_type'] == PACKAGE_PRJ
        assert not os_path_isfile(main_file_path(prj_path, MODULE_PRJ))
        assert os_path_isfile(main_file_path(prj_path, PACKAGE_PRJ))

    def test_new_playground(self, mocked_app_options, empty_repo_path):
        playground_prj_dir = empty_repo_path + '_playground'
        os.rename(empty_repo_path, playground_prj_dir)
        mocked_app_options['project_path'] = playground_prj_dir

        pdv = ProjectDevVars(project_path=playground_prj_dir)
        new_pdv = new_playground(pdv)
        assert new_pdv['project_type'] == PLAYGROUND_PRJ

    def test_new_project_with_namespace(self, module_repo_path):
        files = set(path_items(os_path_join(module_repo_path, "**")))

        new_pdv = renew_project(ProjectDevVars(project_path=module_repo_path))

        assert new_pdv['namespace_name'] == tst_ns_name
        assert new_pdv['portion_name'] == tst_ns_por_pfx + 'module'
        assert new_pdv['project_name'] == tst_pkg_pfx + 'module'
        assert new_pdv['project_type'] == MODULE_PRJ
        assert files < set(path_items(os_path_join(module_repo_path, "**")))

    def test_prepare_children_commit(self, changed_repo_path, empty_repo_path, mocked_app_options, module_repo_path):
        title = "prepare children commit msg title - also adding unstaged files - V {project_version}"
        added = "unstaged_file_to_be_added_by_prepare_action.py"
        test_projects = (changed_repo_path, empty_repo_path, module_repo_path)

        chi_pdvs = []
        uncommitted = {}
        chi_version_files = {}
        for chi_path in test_projects:
            uncommitted[chi_path] = git_uncommitted(chi_path)

            chi_version_files[chi_path] = _ensure_tst_ns_portion_version_file(chi_path)   # needed for changed/empty
            git_checkout(chi_path, new_branch="new_branch_for_test_prepare_children_commit")
            git_add(chi_path)

            write_file(os_path_join(chi_path, added), "# new python module file to be added by prepare action")
            chi_pdvs.append(ProjectDevVars(project_path=chi_path))

        prepare_children_commit(ProjectDevVars(project_path=os_path_dirname(module_repo_path)), title, *chi_pdvs)

        for chi_path in test_projects:
            msg_file_content = read_file(os_path_join(chi_path, COMMIT_MSG_FILE_NAME))
            assert added in msg_file_content, f"with {chi_path=}"
            assert git_uncommitted(chi_path) == uncommitted[chi_path] | {added} | {chi_version_files[chi_path]}
            assert title in msg_file_content.split(os.linesep)[0], f"with {chi_path=}"

    def test_prepare_commit_check_action_errors(self, changed_repo_path, mocked_app_options, patched_exit_call_wrapper):
        mocked_app_options['more_verbose'] = True
        title = "commit msg title"

        cl = patched_exit_call_wrapper(prepare_commit, ProjectDevVars(project_path=changed_repo_path), title)

        assert len(cl) == 1         # _check_action() failed because on main branch with changed/unstaged files
        assert cl[0][0][0] == 13    # '(13, '

    def test_prepare_commit(self, changed_repo_path, empty_repo_path, mocked_app_options, module_repo_path):
        mocked_app_options['more_verbose'] = True
        title = "commit msg title with {project_version} placeholder"
        for prj_path in (changed_repo_path, empty_repo_path, module_repo_path):
            _ensure_tst_ns_portion_version_file(prj_path)   # needed for changed/empty
            git_checkout(prj_path, new_branch="new_branch_for_test_prepare_commit")
            git_add(prj_path)
            assert not os_path_isfile(os_path_join(prj_path, COMMIT_MSG_FILE_NAME))
            uncommitted_files = git_uncommitted(prj_path)
            pdv = ProjectDevVars(project_path=prj_path)

            prepare_commit(pdv, title=title)

            assert os_path_isfile(os_path_join(prj_path, pdv['COMMIT_MSG_FILE_NAME']))
            assert uncommitted_files == git_uncommitted(prj_path)
            assert title in read_file(os_path_join(prj_path, pdv['COMMIT_MSG_FILE_NAME'])).split(os.linesep)[0]

    @skip_gitlab_ci
    def test_refresh_children_outsourced(self, module_repo_path):
        par_pdv = ProjectDevVars(projecT_path=os_path_dirname(module_repo_path))
        chi_pdv = ProjectDevVars(project_path=module_repo_path)
        tst_dir = os_path_join(module_repo_path, TESTS_FOLDER)
        assert not os_path_isdir(tst_dir)

        refresh_children_outsourced(par_pdv, chi_pdv)

        assert os_path_isdir(tst_dir)

    def test_rename_children_file(self, empty_repo_path, mocked_app_options, module_repo_path):
        mocked_app_options['project_path'] = module_repo_path
        mocked_app_options['more_verbose'] = True
        root_pdv = ProjectDevVars(project_path=empty_repo_path)
        root_pdv['project_type'] = ROOT_PRJ
        mod_pdv = ProjectDevVars(project_path=module_repo_path)

        src_file = "ren.efg"
        write_file(os_path_join(empty_repo_path, src_file), "file content")
        write_file(os_path_join(module_repo_path, src_file), "file content")
        dst_file = "renamed.hij"
        assert not os_path_isfile(os_path_join(empty_repo_path, dst_file))
        assert not os_path_isfile(os_path_join(module_repo_path, dst_file))

        assert rename_children_file(root_pdv, src_file, dst_file, mod_pdv)
        assert not os_path_isfile(os_path_join(empty_repo_path, src_file))
        assert os_path_isfile(os_path_join(empty_repo_path, dst_file))
        assert not os_path_isfile(os_path_join(module_repo_path, src_file))
        assert os_path_isfile(os_path_join(module_repo_path, dst_file))

        src_file = os_path_join(tst_ns_name, tst_ns_por_pfx + 'module' + PY_EXT)      # rel path move within prj
        dst_file = tst_ns_por_pfx + 'module' + PY_EXT
        assert os_path_isfile(os_path_join(module_repo_path, src_file))
        assert not os_path_isfile(os_path_join(module_repo_path, dst_file))
        assert not rename_children_file(root_pdv, src_file, dst_file, mod_pdv, mod_pdv)  # no src in root / 2*mod rename
        assert not os_path_isfile(os_path_join(module_repo_path, src_file))
        assert os_path_isfile(os_path_join(module_repo_path, dst_file))

    def test_renew_children(self, empty_repo_path, module_repo_path):
        par_pdv = ProjectDevVars(**{'project_path': os_path_dirname(empty_repo_path)})
        chi_pdv = ProjectDevVars(**{'project_path': module_repo_path})

        renew_children(par_pdv, chi_pdv)

        with patch('ae.shell.git_fetch', return_value=['mocked git fetch error']):
            renew_children(par_pdv, chi_pdv)

    def test_renew_project(self, mocked_app_options, module_repo_path, patched_exit_call_wrapper):
        mocked_app_options['versionIncrementPart'] = 3
        version_file_path = project_main_file(tst_imp_pfx + 'module', project_path=module_repo_path)
        assert code_file_version(version_file_path) == tst_pkg_version

        renew_project(ProjectDevVars(project_path=module_repo_path))

        assert code_file_version(version_file_path) == tst_pkg_version   # not incrementing because no remote repo

    def test_renew_project_version_disabled_version_inc(self, mocked_app_options, module_repo_path):
        version_file_path = project_main_file(tst_imp_pfx + 'module', project_path=module_repo_path)

        mocked_app_options['versionIncrementPart'] = 0

        renew_project(ProjectDevVars(project_path=module_repo_path))

        assert code_file_version(version_file_path) == PDV_NULL_VERSION     # disabled via mocked_app_options

        mocked_app_options.pop('versionIncrementPart')

        renew_project(ProjectDevVars(main_app_options={'versionIncrementPart': 0}, project_path=module_repo_path))

        assert code_file_version(version_file_path) == PDV_NULL_VERSION     # disabled via main_app_options

    def test_run_children_command(self, capsys, empty_repo_path, mocked_app_options):
        mocked_app_options['delay'] = 0
        par_pdv = ProjectDevVars(project_path=os_path_dirname(empty_repo_path))
        chi_pdv = ProjectDevVars(project_path=empty_repo_path)
        echo_word = "tst_run_chi_cmd"

        run_children_command(par_pdv, f"echo {echo_word}", chi_pdv, chi_pdv)

        output = capsys.readouterr().out
        assert output.count(echo_word) == 3  # one for each child and a final one on action complete

    def test_show_actions(self, capsys, changed_repo_path, empty_repo_path, mocked_app_options):
        pdv = ProjectDevVars(**{'host_api': GitlabCom()})

        mocked_app_options['more_verbose'] = False
        show_actions(pdv)
        assert capsys.readouterr().out

        mocked_app_options['more_verbose'] = True
        show_actions(pdv)
        assert capsys.readouterr().out

    def test_show_children_versions(self, capsys):
        chi_grp = 'ae-group'
        chi_prj = 'ae_base'
        chi_ver = "0.3.60"
        with init_parent() as parent_dir:
            parent_pdv = ProjectDevVars(project_path=parent_dir)
            chi_path = clone_project(parent_pdv, f"{chi_grp}/{chi_prj}{PROJECT_VERSION_SEP}{chi_ver}")
            assert chi_path

            show_children_versions(parent_pdv, ProjectDevVars(project_path=chi_path))

            output = capsys.readouterr().out
            assert chi_grp in output
            assert chi_prj in output
            assert f"local:{chi_ver}" in output

    @skip_if_not_maintainer
    def test_update_mirror_pjm_onto_github_org(self, capsys):
        pdv = ProjectDevVars()
        with in_os_env():   # to load GITHUB_TOKEN credential from .env files
            # https://${GITHUB_USERNAME}:${GITHUB_TOKEN}@github.com/{namespace_name}-group-mirror/{project_name}.git
            update_mirror(pdv, _get_mirror_remote(pdv))

        output = capsys.readouterr().out
        assert 'aedev-group-mirror' in output
        assert 'github.com' in output
        assert pdv['project_name'] in output
        assert 'ghp_' not in output   # only the first 3 chars of token ('ghp') will be there
        assert " ==== " in output

    @skip_if_not_maintainer
    def test_update_mirror_pjm_onto_github_user(self, capsys):
        pdv = ProjectDevVars()
        with in_os_env():   # to load GITHUB_TOKEN credential from .env files
            remote = _get_mirror_remote(pdv).replace('aedev-group-mirror', itg_mtn_name)
            # https://${GITHUB_USERNAME}:${GITHUB_TOKEN}@github.com/${PDV_AUTHOR}/{project_name}.git
            update_mirror(pdv, remote)

        output = capsys.readouterr().out
        assert itg_mtn_name in output
        assert 'github.com' in output
        assert pdv['project_name'] in output
        assert 'ghp_' not in output   # only the first 3 chars of token ('ghp') will be there
        assert " ==== " in output

    @skip_if_not_maintainer
    def test_update_mirror_pjm_onto_gitlab_group(self, capsys):
        pdv = ProjectDevVars()
        auth = itg_mtn_name + ":" + itg_mtn_token + "@"
        group = 'aedev-group-mirror'
        url = pdv['REPO_HOST_PROTOCOL'] + auth + pdv['repo_domain'] + "/" + group + "/" + pdv['project_name'] + '.git'

        update_mirror(pdv, url)

        output = capsys.readouterr().out
        assert group in output
        assert pdv['repo_domain'] in output
        assert pdv['project_name'] in output
        assert auth not in output
        assert itg_mtn_token not in output
        assert " ==== " in output

    @skip_if_not_maintainer
    def test_update_mirror_pjm_onto_gitlab_user(self, capsys):
        pdv = ProjectDevVars()
        auth = itg_mtn_name + ":" + itg_mtn_token + "@"
        user = itg_mtn_name
        url = pdv['REPO_HOST_PROTOCOL'] + auth + pdv['repo_domain'] + "/" + user + "/" + pdv['project_name'] + '.git'

        update_mirror(pdv, url)

        output = capsys.readouterr().out
        assert user in output
        assert pdv['repo_domain'] in output
        assert pdv['project_name'] in output
        assert auth not in output
        assert itg_mtn_token not in output
        assert " ==== " in output


class TestHelpersLocal:
    """ test private helper functions that don't need any authentication against git remote hosts. """
    def test_action_decorator(self):
        def test_fun(*_args):
            """ test fun docstring """
            return _args

        try:
            dec = _action(APP_PRJ, MODULE_PRJ, kwarg1='1', kwarg2=2)
            assert callable(dec)
            assert callable(dec(test_fun))
            assert 'test_fun' in REGISTERED_ACTIONS
            assert APP_PRJ in REGISTERED_ACTIONS['test_fun']['project_types']
            assert MODULE_PRJ in REGISTERED_ACTIONS['test_fun']['project_types']
            assert REGISTERED_ACTIONS['test_fun']['docstring'] == " test fun docstring "

            # cae.get_option = lambda opt: "" # prevent argument parsing via cae
            # project_manager_main.ACTION_NAME = 'test_fun'
            # project_manager_main.INI_PDV['project_type'] = APP_PRJ
            assert dec(test_fun)() == ()

        finally:
            REGISTERED_ACTIONS.pop('test_fun', None)

    def test_act_callable(self):
        assert _act_callable(None, 'xxx_yyy_zzz') is None
        assert callable(_act_callable(None, 'new_app'))
        assert not callable(_act_callable(None, 'fork'))
        assert callable(_act_callable(GitlabCom(), 'fork_project'))

    def test_available_actions(self):
        assert _available_actions()
        assert 'show_status' in _available_actions()
        assert 'new_app' in _available_actions()
        assert 'fork_project' in _available_actions()

        assert _available_actions(project_type=NO_PRJ)
        assert 'show_status' not in _available_actions(project_type=NO_PRJ)
        assert 'new_app' in _available_actions(project_type=NO_PRJ)
        assert 'fork_project' not in _available_actions(project_type=NO_PRJ)

    def test_check_arguments(self, patched_exit_call_wrapper):
        pdv = ProjectDevVars(**{'project_type': PARENT_PRJ})
        act_spec = {'docstring': "act new_app docstring", 'project_types': ANY_PRJ_TYPE}

        calls = patched_exit_call_wrapper(_init_act_args_check, pdv, act_spec, 'new_app', [], {})

        assert len(calls) == 1
        assert calls[0][0][0] == 9  # (9, err code
        assert 'new_app' in calls[0][0][1]     # action not available for PARENT_PRJ project type

        pdv['project_type'] = MODULE_PRJ

        assert len(patched_exit_call_wrapper(_init_act_args_check, pdv, act_spec, 'new_app', [], {})) == 0

        calls = patched_exit_call_wrapper(_init_act_args_check, pdv, act_spec, 'new_app', ['argument_value'], {})
        assert len(calls) == 1
        assert calls[0][0][0] == 9  # (9, err code
        assert 'argument_value' in calls[0][0][1]     # unexpected argument

        assert len(patched_exit_call_wrapper(_init_act_args_check, pdv, act_spec, 'show_remote', [], {})) == 0

        calls = patched_exit_call_wrapper(_init_act_args_check, pdv, act_spec, 'show_remote', [], {'zzz': 1})
        assert len(calls) == 1
        assert calls[0][0][0] == 9          # (9, err code for args parse error
        assert 'zzz' in calls[0][0][1]      # unexpected flag arg passed

        pdv['project_type'] = ROOT_PRJ
        assert not patched_exit_call_wrapper(_init_act_args_check, pdv, act_spec, 'install_portions_editable', [], {})

        act_spec['arg_names'] = ((ARG_ALL, ),
                                 ('portions-sets-expr', ),
                                 ('portion-names' + ARG_MULTIPLES, ))
        _init_act_args_check(pdv, act_spec, 'install_portions_editable', [ARG_ALL], {})

        _init_act_args_check(pdv, act_spec, 'install_portions_editable', ['por1', 'por2'], {})

        pdv['project_type'] = APP_PRJ
        _init_act_args_check(pdv, act_spec, 'show_versions', ['p1', 'por2'], {})
        _init_act_args_check(pdv, act_spec, 'show_status', ['por1', 'por2'], {})

        with pytest.raises(KeyError):
            _init_act_args_check(pdv, {}, 'invalid_action', [], {})

    def test_check_arguments_except_empty_action(self):
        with pytest.raises(KeyError):
            _init_act_args_check(ProjectDevVars(), {}, "", [], {})

    def test_expected_args(self):
        spe = {'arg_names': (('varA_arg1', 'varA_arg2'), ('varB_arg1', 'varB_arg2', 'varB_arg3'))}
        assert _expected_args(spe) == "varA_arg1 varA_arg2 -or- varB_arg1 varB_arg2 varB_arg3"

        spe = {'arg_names': (('a', 'b'), ('c', ), ('d', ))}
        assert _expected_args(spe) == "a b -or- c -or- d"

        spe = {'arg_names': (('a', 'b'), ('c', ), ('d', )), 'flags': {'FLAG': False}}
        assert _expected_args(spe).startswith("a b -or- c -or- d")
        assert "FLAG=False" in _expected_args(spe)

        spe = {'flags': {'FLAG': False}}
        assert "FLAG=False" in _expected_args(spe)

    def test_get_branch(self, mocked_app_options, module_repo_path):
        branch = "tst_branch_name"
        mocked_app_options['branch'] = branch
        pdv = ProjectDevVars(project_path=os_path_dirname(module_repo_path))

        assert _get_branch(pdv) == branch

        mocked_app_options['branch'] = ""
        with patch('aedev.project_manager.__main__.git_current_branch', return_value=branch):
            assert _get_branch(pdv) == branch

    def test_get_host_user_name(self, mocked_app_options, module_repo_path, monkeypatch):
        # monkeypatch.delenv('PDV_AUTHOR', raising=False)
        # monkeypatch.delenv('AE_OPTIONS_REPO_USER', raising=False)
        # monkeypatch.delenv('AE_OPTIONS_REPO_USER_AT_GITLAB_COM', raising=False)
        project_path = module_repo_path
        parent_path = os_path_dirname(project_path)
        tst_domain = 'tst_do.main.com'
        t_domain2 = 'test.domain2.tst'

        with in_wd(project_path):   # prevent reading from .env in project_manager root or src parent
            usr_nam = tst_ns_name + PDV_REPO_GROUP_SUFFIX   # default user name for namespace module / module_repo_path

            assert _get_host_user_name(ProjectDevVars(project_path=project_path), "NotGitLabToIgnoreLocEnvs") == usr_nam

            # tests ordered by priority; first test with the lowest priority: get .env variable w/o domain in parent dir

            usr_nam = "usr_nam_via_group_name_command_line_option"
            mocked_app_options['repo_group'] = usr_nam

            assert _get_host_user_name(ProjectDevVars(project_path=project_path), "") == usr_nam

            var_nam = f"{ENV_VAR_NAME_PREFIX}repo_user"
            usr_nam = 'usr_nam_via_PDV_var_in_parent_.env'
            write_file(os_path_join(parent_path, ".env"), f"\n{var_nam}={usr_nam}\n", extra_mode='a')

            assert _get_host_user_name(ProjectDevVars(project_path=project_path), "") == usr_nam
            assert _get_host_user_name(ProjectDevVars(project_path=project_path), tst_domain) == usr_nam

            var_nam = f"{ENV_VAR_NAME_PREFIX}repo_user"
            usr_nam = 'usr_nam_via_PDV_var_in_.env'
            write_file(os_path_join(project_path, ".env"), f"\n{var_nam}={usr_nam}\n", extra_mode='a')

            assert _get_host_user_name(ProjectDevVars(project_path=project_path), tst_domain) == usr_nam
            assert _get_host_user_name(ProjectDevVars(project_path=project_path), "") == usr_nam

            var_nam = f"{ENV_VAR_NAME_PREFIX}repo_user"
            usr_nam = 'usr_nam_via_PDV_var_in_os.environ'
            monkeypatch.setenv(var_nam, usr_nam)

            assert _get_host_user_name(ProjectDevVars(project_path=project_path), "") == usr_nam
            assert _get_host_user_name(ProjectDevVars(project_path=project_path), t_domain2) == usr_nam

            var_nam = "AE_OPTIONS_REPO_USER"
            usr_nam = 'usr_nam_via_parent_.env_and_without_domain'
            write_file(os_path_join(parent_path, ".env"), f"\n{var_nam}={usr_nam}\n", extra_mode='a')

            assert _get_host_user_name(ProjectDevVars(project_path=project_path), "") == usr_nam

            var_nam = f"AE_OPTIONS_REPO_USER_AT_{norm_name(tst_domain).upper()}"
            usr_nam = 'usr_nam_via_parent_.env_and_with_domain'
            write_file(os_path_join(parent_path, ".env"), f"\n{var_nam}={usr_nam}\n", extra_mode='a')

            assert _get_host_user_name(ProjectDevVars(project_path=project_path), tst_domain) == usr_nam

            var_nam = "AE_OPTIONS_REPO_USER"
            usr_nam = 'usr_nam_via_.env_and_without_domain'
            write_file(os_path_join(project_path, ".env"), f"\n{var_nam}={usr_nam}\n", extra_mode='a')

            assert _get_host_user_name(ProjectDevVars(project_path=project_path), "") == usr_nam

            var_nam = f"AE_OPTIONS_REPO_USER_AT_{norm_name(tst_domain).upper()}"
            usr_nam = 'usr_nam_via_.env_and_with_domain'
            write_file(os_path_join(parent_path, ".env"), f"\n{var_nam}={usr_nam}\n", extra_mode='a')

            assert _get_host_user_name(ProjectDevVars(project_path=project_path), tst_domain) == usr_nam

            var_nam = "AE_OPTIONS_REPO_USER"
            usr_nam = 'usr_nam_via_environ_and_without_domain'
            monkeypatch.setenv(var_nam, usr_nam)

            assert _get_host_user_name(ProjectDevVars(project_path=project_path), "") == usr_nam

            var_nam = f"AE_OPTIONS_REPO_USER_AT_{norm_name(tst_domain).upper()}"
            usr_nam = 'usr_nam_via_environ_and_with_domain'
            monkeypatch.setenv(var_nam, usr_nam)

            assert _get_host_user_name(ProjectDevVars(project_path=project_path), tst_domain) == usr_nam

            var_nam = f"AE_OPTIONS_REPO_USER_AT_{norm_name(t_domain2).upper()}"
            usr_nam = 'usr_nam_via_.env_and_with_domain_set_via_command_line_option'
            mocked_app_options['repo_domain'] = t_domain2
            write_file(os_path_join(parent_path, ".env"), f"\n{var_nam}={usr_nam}\n", extra_mode='a')

            assert _get_host_user_name(ProjectDevVars(project_path=project_path), "") == usr_nam
            assert _get_host_user_name(ProjectDevVars(project_path=project_path), t_domain2) == usr_nam

            usr_nam = "usr_nam_via_command_line_option"
            mocked_app_options['repo_user'] = usr_nam

            assert _get_host_user_name(ProjectDevVars(project_path=project_path), tst_domain) == usr_nam

    def test_get_host_user_token(self, empty_repo_path, mocked_app_options, monkeypatch):
        # these tests would fail ONLY if run via "pjm check" because the tokens get loaded from .env by pjm
        for env_var in os.environ:
            if "REPO_TOKEN" in env_var.upper():  # AE_OPTIONS... or PDV_repo_token
                print(f"   ## temp. unload of variable {env_var} for unit test")
                monkeypatch.delenv(env_var)

        parent_path = os_path_dirname(empty_repo_path)
        tst_domain = 't.s.t_do.main.com'
        t_domain2 = 't.s.t.domain2.t.st'
        user_name = 'TstUserName'

        with in_wd(empty_repo_path):  # prevent reading from .env in ProjectDevVars([project_path="."]) instantiation
            usr_tok = ""  # user token default is an empty string

            assert _get_host_user_token(ProjectDevVars(), "NotGitLabToIgnoreLocEnvs") == usr_tok

            # tests ordered by priority; first test with the lowest priority: get .env variable w/o domain in parent dir

            var_nam = f"{ENV_VAR_NAME_PREFIX}repo_token"
            usr_tok = 'usr_tok_via_PDV_var_in_parent_.env'
            write_file(os_path_join(parent_path, ".env"), f"\n{var_nam}={usr_tok}\n", extra_mode='a')

            assert _get_host_user_token(ProjectDevVars(), "") == usr_tok
            assert _get_host_user_token(ProjectDevVars(), tst_domain) == usr_tok

            var_nam = f"{ENV_VAR_NAME_PREFIX}repo_token"
            usr_tok = 'usr_tok_via_PDV_var_in_.env'
            write_file(".env", f"\n{var_nam}={usr_tok}\n", extra_mode='a')

            assert _get_host_user_token(ProjectDevVars(), tst_domain) == usr_tok
            assert _get_host_user_token(ProjectDevVars(), "") == usr_tok

            var_nam = f"{ENV_VAR_NAME_PREFIX}repo_token"
            usr_tok = 'usr_tok_via_PDV_var_in_os.environ'
            monkeypatch.setenv(var_nam, usr_tok)

            assert _get_host_user_token(ProjectDevVars(), "") == usr_tok
            assert _get_host_user_token(ProjectDevVars(), t_domain2) == usr_tok

            var_nam = "AE_OPTIONS_REPO_TOKEN"
            usr_tok = 'usr_tok_via_parent_.env_and_without_domain'
            write_file(os_path_join(parent_path, ".env"), f"\n{var_nam}={usr_tok}\n", extra_mode='a')

            assert _get_host_user_token(ProjectDevVars(), "") == usr_tok

            var_nam = f"AE_OPTIONS_REPO_TOKEN_AT_{norm_name(tst_domain).upper()}"
            usr_tok = 'usr_tok_via_parent_.env_and_with_domain'
            write_file(os_path_join(parent_path, ".env"), f"\n{var_nam}={usr_tok}\n", extra_mode='a')

            assert _get_host_user_token(ProjectDevVars(), tst_domain) == usr_tok

            var_nam = f"AE_OPTIONS_REPO_TOKEN_AT_{norm_name(tst_domain).upper()}_{user_name.upper()}"
            usr_tok = 'usr_tok_via_parent_.env_and_with_domain_and_user'
            write_file(os_path_join(parent_path, ".env"), f"\n{var_nam}={usr_tok}\n", extra_mode='a')

            assert _get_host_user_token(ProjectDevVars(), tst_domain, host_user=user_name) == usr_tok

            var_nam = "AE_OPTIONS_REPO_TOKEN"
            usr_tok = 'usr_tok_via_.env_and_without_domain'
            write_file(".env", f"\n{var_nam}={usr_tok}\n", extra_mode='a')

            assert _get_host_user_token(ProjectDevVars(), "") == usr_tok

            var_nam = f"AE_OPTIONS_REPO_TOKEN_AT_{norm_name(tst_domain).upper()}"
            usr_tok = 'usr_tok_via_.env_and_with_domain'
            write_file(os_path_join(parent_path, ".env"), f"\n{var_nam}={usr_tok}\n", extra_mode='a')

            assert _get_host_user_token(ProjectDevVars(), tst_domain) == usr_tok

            var_nam = f"AE_OPTIONS_REPO_TOKEN_AT_{norm_name(tst_domain).upper()}_{user_name.upper()}"
            usr_tok = 'usr_tok_via_.env_and_with_domain_and_user'
            write_file(os_path_join(parent_path, ".env"), f"\n{var_nam}={usr_tok}\n", extra_mode='a')

            assert _get_host_user_token(ProjectDevVars(), tst_domain, host_user=user_name) == usr_tok

            var_nam = "AE_OPTIONS_REPO_TOKEN"
            usr_tok = 'usr_tok_via_environ_and_without_domain'
            monkeypatch.setenv(var_nam, usr_tok)

            assert _get_host_user_token(ProjectDevVars(), "") == usr_tok

            var_nam = f"AE_OPTIONS_REPO_TOKEN_AT_{norm_name(tst_domain).upper()}"
            usr_tok = 'usr_tok_via_environ_and_with_domain'
            monkeypatch.setenv(var_nam, usr_tok)

            assert _get_host_user_token(ProjectDevVars(), tst_domain) == usr_tok

            var_nam = f"AE_OPTIONS_REPO_TOKEN_AT_{norm_name(tst_domain).upper()}_{user_name.upper()}"
            usr_tok = 'usr_tok_via_environ_and_with_domain_and_user'
            monkeypatch.setenv(var_nam, usr_tok)

            assert _get_host_user_token(ProjectDevVars(), tst_domain, host_user=user_name) == usr_tok

            var_nam = f"AE_OPTIONS_REPO_TOKEN_AT_{norm_name(t_domain2).upper()}"
            usr_tok = 'usr_tok_via_.env_and_with_domain_set_via_command_line_option'
            mocked_app_options['repo_domain'] = t_domain2
            write_file(os_path_join(parent_path, ".env"), f"\n{var_nam}={usr_tok}\n", extra_mode='a')

            assert _get_host_user_token(ProjectDevVars(), "") == usr_tok
            assert _get_host_user_token(ProjectDevVars(), t_domain2) == usr_tok

            var_nam = f"AE_OPTIONS_REPO_TOKEN_AT_{norm_name(t_domain2).upper()}_{user_name.upper()}"
            usr_tok = 'usr_tok_via_.env_and_with_domain_set_via_command_line_option_and_with_user'
            mocked_app_options['repo_domain'] = t_domain2
            write_file(os_path_join(parent_path, ".env"), f"\n{var_nam}={usr_tok}\n", extra_mode='a')

            assert _get_host_user_token(ProjectDevVars(), "", host_user=user_name) == usr_tok
            assert _get_host_user_token(ProjectDevVars(), t_domain2, host_user=user_name) == usr_tok

            usr_tok = "usr_tok_via_command_line_option"
            mocked_app_options['repo_token'] = usr_tok

            assert _get_host_user_token(ProjectDevVars(), tst_domain) == usr_tok

        token = "t_s_t__usr_token"
        pdv = ProjectDevVars(project_path=empty_repo_path)

        mocked_app_options['repo_token'] = token
        assert _get_host_user_token(pdv, "") == token
        assert _get_host_user_token(pdv, "", host_user="not_configured_user_name") == token

        with patch('aedev.project_manager.__main__._get_host_group', return_value=token):
            assert _get_host_user_token(pdv, "domain.xxx") == token
            assert _get_host_user_token(pdv, "not_configured_domain", host_user="not_configured_user_name") == token

    def test_guess_next_action_on_local_machine_only(self, empty_repo_path):
        git_checkout(empty_repo_path, "--detach")

        ret = _guess_next_action(ProjectDevVars(project_path=empty_repo_path))

        assert ret.startswith("¡detached HEAD")

        git_checkout(empty_repo_path, DEF_MAIN_BRANCH)

        ret = _guess_next_action(ProjectDevVars(project_path=empty_repo_path))

        assert ret.startswith("¡empty or invalid project version")

        _ensure_tst_ns_portion_version_file(empty_repo_path)

        ret = _guess_next_action(ProjectDevVars(project_path=empty_repo_path))

        assert ret.startswith(uncommitted_guess_prefix)

        new_branch = 'new_feature_branch_name_testing_guest_next_action' + now_str(sep="_")
        git_checkout(empty_repo_path, new_branch=new_branch)

        ret = _guess_next_action(ProjectDevVars(project_path=empty_repo_path))

        assert ret.startswith(f"¡unstaged files found")

        git_add(empty_repo_path)

        ret = _guess_next_action(ProjectDevVars(project_path=empty_repo_path))

        assert ret == 'prepare_commit'

        write_file(os_path_join(empty_repo_path, COMMIT_MSG_FILE_NAME), "msg-title without project_version placeholder")

        ret = _guess_next_action(ProjectDevVars(project_path=empty_repo_path))

        assert ret == 'prepare_commit'

        write_file(os_path_join(empty_repo_path, COMMIT_MSG_FILE_NAME), "msg-title V {project_version}")

        ret = _guess_next_action(ProjectDevVars(project_path=empty_repo_path))

        assert ret == 'commit_project'

        git_commit(empty_repo_path, tst_pkg_version)
        git_checkout(empty_repo_path, DEF_MAIN_BRANCH)
        _ensure_tst_ns_portion_version_file(empty_repo_path)
        git_add(empty_repo_path)
        git_commit(empty_repo_path, tst_pkg_version)

        ret = _guess_next_action(ProjectDevVars(project_path=empty_repo_path))

        assert ret == 'renew_project'

        # NOT TESTABLE because ret.startswith("¡detached HEAD") if .git gets renamed
        # os.rename(os_path_join(empty_repo_path, ".git"), os_path_join(empty_repo_path, '_renamed_git_folder'))
        #
        # ret = _guess_next_action(ProjectDevVars(project_path=empty_repo_path))
        #
        # assert ret.startswith("¡no git workflow initiated")
        # assert "start a new project" in ret
        #
        # os.rename(os_path_join(empty_repo_path, '_renamed_git_folder'), os_path_join(empty_repo_path, ".git"))

        git_checkout(empty_repo_path, new_branch)

        ret = _guess_next_action(ProjectDevVars(project_path=empty_repo_path))

        assert ret == 'push_project'

    def test_guess_next_action_fix_empty_on_local_machine_only(self, empty_repo_path):
        assert _guess_next_action(ProjectDevVars(project_path=empty_repo_path)).startswith("¡")

        _ensure_tst_ns_portion_version_file(empty_repo_path)
        git_checkout(empty_repo_path, new_branch='new_feature_branch_name_testing_guest_next_action' + now_str(sep="_"))
        write_file(os_path_join(empty_repo_path, COMMIT_MSG_FILE_NAME), "msg-title V {project_version}")
        git_add(empty_repo_path)

        assert _guess_next_action(ProjectDevVars(project_path=empty_repo_path)) == 'commit_project'

    def test_init_act_exec_args_check_deploy(self, empty_repo_path, mocked_app_options):
        mocked_app_options['action'] = 'check_deploy'
        mocked_app_options['arguments'] = ['WORKTREE', 'ALL', 'MASKS=["file_mask1", "file_mask2"]']
        mocked_app_options['web_domain'] = 'eu.pythonanywhere.com'
        mocked_app_options['project_path'] = empty_repo_path
        write_file(os_path_join(empty_repo_path, 'manage.py'), "content")   # to be recognized as a django project type

        ini_pdv, act_name, act_args, act_flags = _init_act_exec_args()

        assert isinstance(ini_pdv, dict)    # ProjectDevVars
        assert 'host_api' in ini_pdv
        assert act_name == 'check_deploy'
        assert act_args == ['WORKTREE']
        assert act_flags['ALL'] is True
        assert act_flags['MASKS'] == ["file_mask1", "file_mask2"]
        assert act_flags['CLEANUP'] is False

    def test_init_act_exec_args_exits(self, mocked_app_options, patched_exit_call_wrapper):
        mocked_app_options['action'] = 'what_ever_not_existing_action'
        mocked_app_options['arguments'] = ['what_ever_invalid_action_arg']

        assert patched_exit_call_wrapper(_init_act_exec_args)

    def test_init_act_exec_args_new_app(self, mocked_app_options):
        mocked_app_options['action'] = 'new_app'
        mocked_app_options['arguments'] = []

        ini_pdv, act_name, act_args, act_flags = _init_act_exec_args()

        assert isinstance(ini_pdv, dict)    # ProjectDevVars
        assert 'host_api' not in ini_pdv
        assert act_name == 'new_app'
        assert act_args == []
        assert act_flags == {}

    def test_init_act_exec_args_for_local_action_show_versions(self, mocked_app_options, module_repo_path):
        mocked_app_options['action'] = 'show-versions'
        mocked_app_options['arguments'] = []
        mocked_app_options['project_path'] = module_repo_path

        ini_pdv, act_name, act_args, act_flags = _init_act_exec_args()

        assert isinstance(ini_pdv, dict)    # ProjectDevVars
        assert act_name == 'show_versions'
        assert act_args == []
        assert act_flags == {}
        assert 'host_api' not in ini_pdv

    def test_init_children_pdv_args_branch_filter(self):
        filtered_branch = "tst_filtered_branch_name"
        ch1_pdv = ProjectDevVars(**{'project_path': 'n_a'})
        ch2_pdv = ProjectDevVars(**{'project_path': 'n_b'})
        par_pdv = ProjectDevVars(**{'children_project_vars': {'n_a': ch1_pdv, 'n_b': ch2_pdv},
                                    'namespace_name': 'n',
                                    'portions_packages': ['n_a', 'n_b']})

        assert _init_children_pdv_args(par_pdv, [ARG_ALL]) == [ch1_pdv, ch2_pdv]

        with patch('aedev.project_manager.__main__.git_current_branch',
                   new=lambda _: filtered_branch if _.endswith('n_b') else DEF_MAIN_BRANCH):
            par_pdv['main_app_options'] = {'filterBranch': filtered_branch}
            assert _init_children_pdv_args(par_pdv, ['filterBranch']) == [ch2_pdv]

    def test_init_children_pdv_args_exit(self, mocked_app_options, patched_exit_call_wrapper):
        ini_pdv = ProjectDevVars(**{'children_project_vars': {}, 'namespace_name': "nn"})

        assert len(patched_exit_call_wrapper(_init_children_pdv_args, ini_pdv, [])) == 1    # missing/empty args

        assert len(patched_exit_call_wrapper(_init_children_pdv_args, ini_pdv, ["undefined_project_nam"])) == 0  # noErr

        assert len(patched_exit_call_wrapper(_init_children_pdv_args, ini_pdv, ["filterBranch"])) == 1  # missing branch

        mocked_app_options['filterBranch'] = "branch_name_to_filter"

        assert len(patched_exit_call_wrapper(_init_children_pdv_args, ini_pdv, [ARG_ALL])) == 1

    def test_init_children_pdv_args_expression(self, temp_parent_path):
        par_pdv = ProjectDevVars(**{'project_path': temp_parent_path, 'project_type': PARENT_PRJ})
        ch1_pdv = ProjectDevVars(**{'project_path': os_path_join(temp_parent_path, 'p1')})
        ch2_pdv = ProjectDevVars(**{'project_path': os_path_join(temp_parent_path, 'p2')})
        chi_vars = {'p1': ch1_pdv, 'p2': ch2_pdv}
        par_pdv['children_project_vars'] = chi_vars

        assert _init_children_pdv_args(par_pdv, ['any_pkg_nam']) == [
            ProjectDevVars(**{'project_path': os_path_join(temp_parent_path, 'any_pkg_nam')})]

        with patch('aedev.project_manager.__main__._init_children_presets',
                   return_value={'ps_a': {'p1'}, 'ps_b': {'p1', 'p2'}}):
            assert _init_children_pdv_args(par_pdv, ["ps_a"]) == [ch1_pdv]
            assert ch1_pdv in _init_children_pdv_args(par_pdv, ["ps_b"])
            assert ch2_pdv in _init_children_pdv_args(par_pdv, ["ps_b"])
            assert _init_children_pdv_args(par_pdv, ["ps_b - ps_a"]) == [ch2_pdv]

        par_pdv['namespace_name'] = 'n'
        ch1_pdv = {'project_name': "n_1", 'project_path': temp_parent_path}
        ch2_pdv = {'project_name': "n_por2", 'project_path': temp_parent_path}
        ch3_pdv = {'project_name': "n_b", 'project_path': temp_parent_path}
        par_pdv['children_project_vars'] = {'n_1': ch1_pdv, 'n_por2': ch2_pdv, 'n_b': ch3_pdv}
        with patch('aedev.project_manager.__main__._init_children_presets',
                   return_value={'ps_a': {'n_1', 'n_b'}, 'ps_b': {'n_1', 'n_por2'}, 'ps_c': {'n_por2'}}):
            assert _init_children_pdv_args(par_pdv, ["ps_a ^ (ps_b - ps_c)"]) == [ch3_pdv]

            assert ch1_pdv in _init_children_pdv_args(par_pdv, ["ps_a | (ps_b - ps_c)"])
            assert ch3_pdv in _init_children_pdv_args(par_pdv, ["ps_a | (ps_b - ps_c)"])

            assert _init_children_pdv_args(par_pdv, ["ps_a & ps_b"]) == [ch1_pdv]
            assert _init_children_pdv_args(par_pdv, ["ps_b & ps_c"]) == [ch2_pdv]

            assert _init_children_pdv_args(par_pdv, ["set(ps_a) & (ps_b - set(['n_por2']))"]) == [ch1_pdv]

            assert _init_children_pdv_args(par_pdv, ["ps_a&ps_b"]) == [ch1_pdv]
            assert _init_children_pdv_args(par_pdv, ["ps_a", "&", "ps_b"]) == [ch1_pdv]

    def test_init_children_pdv_args_list(self, empty_repo_path, mocked_app_options):
        par_dir = os_path_dirname(empty_repo_path)
        par_pdv = ProjectDevVars(**{'project_path': par_dir, 'project_type': PARENT_PRJ})
        ch1_dir = os_path_join(par_dir, 'p1')
        ch1_pdv = ProjectDevVars(**{'project_path': ch1_dir})
        ch2_dir = os_path_join(par_dir, 'p2')
        ch2_pdv = ProjectDevVars(**{'project_path': ch2_dir})
        chi_vars = {'p1': ch1_pdv, 'p2': ch2_pdv}
        par_pdv['children_project_vars'] = chi_vars

        assert _init_children_pdv_args(par_pdv, ["('p1', ) + ('p2', )"]) == [ch1_pdv, ch2_pdv]

        with in_wd(par_dir):
            chi_vars = {key: ProjectDevVars(**{'project_name': key}) for key in ['a1', 'b', 'p3']}
        par_pdv['children_project_vars'] = chi_vars

        assert _init_children_pdv_args(par_pdv, [ARG_ALL]) == list(chi_vars.values())

        ch3_dir = os_path_join(os_path_dirname(empty_repo_path), 'p3')
        chi_pdvs = _init_children_pdv_args(par_pdv, ['p3'])

        assert len(chi_pdvs) == 1
        assert chi_pdvs[0]['project_name'] == 'p3'
        assert chi_pdvs[0]['project_path'] == ch3_dir

        mocked_app_options['force'] = 1      # ignore 1 warning/error of duplicate child p3

        chi_pdvs = _init_children_pdv_args(par_pdv, ['p3', 'p3'])

        assert chi_pdvs[0]['project_name'] == chi_pdvs[1]['project_name'] == 'p3'
        assert chi_pdvs[0]['project_path'] == chi_pdvs[1]['project_path'] == ch3_dir

        nsn = 'n'
        ch1_pdv = ProjectDevVars(**{'project_path': os_path_join(par_dir, nsn + "_1")})
        ch2_pdv = ProjectDevVars(**{'project_path': os_path_join(par_dir, nsn + "_por2")})
        chi_vars = {nsn + '_1': ch1_pdv, nsn + '_por2': ch2_pdv}
        par_pdv = ProjectDevVars(**{'project_path': os_path_join(par_dir, nsn + "_" + nsn),
                                    'children_project_vars': chi_vars, 'namespace_name': nsn, 'project_type': ROOT_PRJ})

        assert _init_children_pdv_args(par_pdv, ["('1', ) + ('n_por2', )"]) == [ch1_pdv, ch2_pdv]

    def test_init_children_presets(self, empty_repo_path):
        pkg_name = os_path_basename(empty_repo_path)
        par = ProjectDevVars(**{'project_path': os_path_dirname(empty_repo_path),
                                'main_app_options': {'filterBranch': DEF_MAIN_BRANCH, 'filterExpression': "True"}})
        chi = ProjectDevVars(**{'project_path': empty_repo_path, 'editable_project_path': empty_repo_path})

        with (patch('aedev.project_manager.__main__.git_uncommitted', return_value=["any-non-empty-value"]),
              patch('aedev.project_manager.__main__.git_current_branch', return_value=DEF_MAIN_BRANCH)):
            presets = _init_children_presets(par, OrderedDict({pkg_name: chi}))

        assert len(presets) == 6
        assert presets[ARG_ALL] == {pkg_name}
        assert presets['editable'] == {pkg_name}
        assert presets['modified'] == {pkg_name}
        assert presets['develop'] == {pkg_name}
        assert presets['filterBranch'] == {pkg_name}
        assert presets['filterExpression'] == {pkg_name}

        del par.pdv_val('main_app_options')['filterBranch']
        par['main_app_options'] = chi['main_app_options'] = {'filterExpression': ":invalid:exp+ess+on"}

        with (patch('aedev.project_manager.__main__.git_uncommitted', return_value=[]),
              patch('aedev.project_manager.__main__.git_current_branch', return_value="any-other-but-DEF_MAIN_BRANCH")):
            presets = _init_children_presets(par, OrderedDict({pkg_name: chi}))

        assert len(presets) == 5
        assert presets[ARG_ALL] == {pkg_name}
        assert presets['editable'] == {pkg_name}
        assert presets['modified'] == set()  # because patched git_uncommitted, else ??.gitignore would be returned
        assert presets['develop'] == set()  # because of patched git_current_branch, empty_repo_path has DEF_MAIN_BRANCH
        assert 'filterBranch' not in presets
        assert presets['filterExpression'] == set()  # invalid expression evaluates to False

    def test_print_pdv(self):
        _print_pdv(ProjectDevVars(**{'project_type': PARENT_PRJ, 'long_desc_content': "not that long desc content"}))
        # assert capsys.readouterr().out worked in TestHiddenHelpersRemote, but after moving here is always empty string

    def test_refresh_templates_empty_folder(self, tmp_path):
        assert not _refresh_templates(ProjectDevVars(project_path=str(tmp_path)))

    def test_refresh_templates_new_module_prj(self, module_repo_path):
        assert _refresh_templates(ProjectDevVars(project_path=module_repo_path))

    def test_refresh_templates_no_prj(self, empty_repo_path, changed_repo_path):
        assert not _refresh_templates(ProjectDevVars(project_path=empty_repo_path))
        assert not _refresh_templates(ProjectDevVars(project_path=changed_repo_path))

    def test_refresh_templates_test_registered(self, tmp_path):
        parent_dir = os_path_join(str(tmp_path), DEF_PROJECT_PARENT_FOLDER)
        namespace = "nsn"
        project_name = f"{namespace}_pkg_name"
        project_path = norm_path(os_path_join(parent_dir, project_name))
        prj_tpls = [
            {'import_name': namespace + '.' + namespace,
             'tpl_path': os_path_join(parent_dir, namespace + '_' + namespace, namespace, namespace, TEMPLATES_FOLDER),
             'version': '1.1.1',
             'register_message': "manually setup for unit testing"},
            {'import_name': TPL_IMPORT_NAME_PREFIX + 'project' + TPL_IMPORT_NAME_SUFFIX,
             'tpl_path': os_path_join(parent_dir, 'aedev_package_tpls', 'aedev', 'package_tpls', TEMPLATES_FOLDER),
             'version': '3.3.3',
             'register_message': "manually setup for unit testing"},
            {'import_name': TPL_IMPORT_NAME_PREFIX + 'project' + TPL_IMPORT_NAME_SUFFIX,
             'tpl_path': os_path_join(parent_dir, 'aedev_project_tpls', 'aedev', 'project_tpls', TEMPLATES_FOLDER),
             'version': '9.9.9',
             'register_message': "manually setup for unit testing"},
        ]
        pdv = ProjectDevVars(**{'namespace_name': namespace, 'project_path': project_path, 'project_type': PACKAGE_PRJ,
                                'project_templates': []})
        _renew_prj_dir(pdv)

        assert not _refresh_templates(pdv)

        deep_sub_dir = os_path_join('deeper', 'even_deeper')
        file_for_all = 'file_for_all.ext'
        tpl_file_for_all = OUTSOURCED_FILE_NAME_PREFIX + TPL_FILE_NAME_PREFIX + file_for_all
        for tpl_reg in prj_tpls:
            tpl_path = os_path_join(tpl_reg['tpl_path'], deep_sub_dir)
            write_file(os_path_join(tpl_path, tpl_file_for_all), tpl_reg['tpl_path'], make_dirs=True)
        tpl_file = os_path_join(project_path, deep_sub_dir, file_for_all)

        # 2nd test with template in all templates (root prj has the highest priority)
        pdv = ProjectDevVars(**{'namespace_name': namespace, 'project_path': project_path,
                                'project_type': PACKAGE_PRJ,
                                'TEMPLATES_FOLDER': TEMPLATES_FOLDER, 'project_templates': prj_tpls})

        assert _refresh_templates(pdv) == {norm_path(tpl_file)}

        assert os_path_isfile(tpl_file)
        content = read_file(tpl_file)
        assert prj_tpls[0]['tpl_path'] in content
        assert OUTSOURCED_MARKER in content

    def test_refresh_templates_file_include_content(self, tmp_path):
        parent_dir = os_path_join(str(tmp_path), DEF_PROJECT_PARENT_FOLDER)
        tpl_pkg_path = norm_path(os_path_join(parent_dir, 'tst_tpls', TEMPLATES_FOLDER))
        tpl_file_name = "including_content.txt"
        tpl_file_path = os_path_join(tpl_pkg_path, OUTSOURCED_FILE_NAME_PREFIX + TPL_FILE_NAME_PREFIX + tpl_file_name)
        ver = '9.6.9999'
        project_templates = [{'import_name': TPL_IMPORT_NAME_PREFIX + 'project' + TPL_IMPORT_NAME_SUFFIX,
                              'tpl_path': tpl_pkg_path,
                              'version': ver,
                              'register_message': "manually setup for unit testing"}]
        included_file_name = norm_path(os_path_join(parent_dir, "inc.tst.file"))
        included_file_content = "replacement string"
        project_name = f"prj_name"
        project_path = os_path_join(parent_dir, project_name)
        patched_file_name = os_path_join(project_path, tpl_file_name)
        os.makedirs(project_path)
        os.makedirs(tpl_pkg_path)

        tpl = f"{TEMPLATE_PLACEHOLDER_ID_PREFIX}{TEMPLATE_INCLUDE_FILE_PLACEHOLDER_ID}"
        tpl += f"{TEMPLATE_PLACEHOLDER_ID_SUFFIX}{included_file_name}{TEMPLATE_PLACEHOLDER_ARGS_SUFFIX}"
        write_file(tpl_file_path, tpl)
        write_file(included_file_name, included_file_content)

        with in_wd(project_path):
            patched = _refresh_templates(ProjectDevVars(project_type=MODULE_PRJ, project_templates=project_templates))

        assert patched == {norm_path(patched_file_name)}

        content = read_file(patched_file_name)
        assert included_file_content in content
        assert ver in content
        assert "TEMPLATE_PLACEHOLDER_ID_PREFIX" not in content
        assert TEMPLATE_INCLUDE_FILE_PLACEHOLDER_ID not in content
        assert "TEMPLATE_INCLUDE_FILE_PLACEHOLDER_ID" not in content
        assert TEMPLATE_PLACEHOLDER_ID_SUFFIX not in content
        assert "TEMPLATE_PLACEHOLDER_ID_SUFFIX" not in content
        assert TEMPLATE_PLACEHOLDER_ARGS_SUFFIX not in content
        assert "TEMPLATE_PLACEHOLDER_ARGS_SUFFIX" not in content

    def test_refresh_templates_file_include_default_and_with_pdv_vars(self, mocked_app_options, monkeypatch, tmp_path):
        parent_dir = os_path_join(str(tmp_path), DEF_PROJECT_PARENT_FOLDER)
        namespace_name = "tns"
        portion_name = 'destination_portion_name'
        project_path = os_path_join(parent_dir, f'{namespace_name}_{portion_name}')
        package_path = os_path_join(project_path, namespace_name)
        patched_file = "including_content.txt"
        patched_path = os_path_join(project_path, patched_file)

        tpl_imp_name = namespace_name + '.' + namespace_name
        tpl_pkg_path = norm_path(os_path_join(
            parent_dir, norm_name(tpl_imp_name), namespace_name, namespace_name, TEMPLATES_FOLDER))
        tpl_file_path = os_path_join(tpl_pkg_path, OUTSOURCED_FILE_NAME_PREFIX + TPL_FILE_NAME_PREFIX + patched_file)

        default = "include file default string"
        version = '6.699.987'

        mocked_app_options[template_version_option(tpl_imp_name)] = version
        mocked_app_options['namespace_name'] = namespace_name    # or ""
        os.makedirs(package_path)
        write_file(os_path_join(project_path, PDV_REQ_DEV_FILE_NAME), norm_name(tpl_imp_name))
        write_file(os_path_join(package_path, portion_name + PY_EXT), "__version__ = '9.6.3'")

        os.makedirs(os_path_dirname(tpl_file_path))
        tpl = "{TEMPLATE_PLACEHOLDER_ID_PREFIX}{TEMPLATE_INCLUDE_FILE_PLACEHOLDER_ID}"
        tpl += "{TEMPLATE_PLACEHOLDER_ID_SUFFIX}"
        tpl += f"not_existing_included_file_name.ext,{default}"
        tpl += "{TEMPLATE_PLACEHOLDER_ARGS_SUFFIX}"
        write_file(tpl_file_path, tpl)

        monkeypatch.setitem(CACHED_TPL_PROJECTS, tpl_imp_name + PROJECT_VERSION_SEP + version,
                            {'import_name': tpl_imp_name, 'tpl_path': tpl_pkg_path, 'version': version,
                             'register_message': "manually setup for unit testing"})

        pdv = ProjectDevVars(project_path=project_path)

        patched_file_paths = _refresh_templates(pdv)

        assert 'project_templates' in pdv
        assert os_path_isfile(patched_path)
        assert norm_path(patched_path) in patched_file_paths

        content = read_file(patched_path)
        assert default in content
        assert tpl_imp_name in content
        assert version in content
        assert "TEMPLATE_PLACEHOLDER_ID_PREFIX" not in content
        assert TEMPLATE_INCLUDE_FILE_PLACEHOLDER_ID not in content
        assert "TEMPLATE_INCLUDE_FILE_PLACEHOLDER_ID" not in content
        assert TEMPLATE_PLACEHOLDER_ID_SUFFIX not in content
        assert "TEMPLATE_PLACEHOLDER_ID_SUFFIX" not in content
        assert TEMPLATE_PLACEHOLDER_ARGS_SUFFIX not in content
        assert "TEMPLATE_PLACEHOLDER_ARGS_SUFFIX" not in content

    def test_renew_prj_dir(self, mocked_app_options, tmp_path):
        parent_dir = os_path_join(str(tmp_path), DEF_PROJECT_PARENT_FOLDER)
        app_name = 'cpl_prj_dir_app'
        project_path = norm_path(os_path_join(parent_dir, app_name))
        package_path = os_path_join(project_path, 'tpl_src_no_namespace')
        mocked_app_options['repo_group'] = "group_name"
        mocked_app_options['project_name'] = app_name
        mocked_app_options['project_path'] = project_path
        pdv = ProjectDevVars(**{
            'namespace_name': '',
            'project_path': project_path,
            'package_path': package_path,
            'project_type': APP_PRJ})

        assert not os_path_isdir(project_path)

        _renew_prj_dir(pdv.copy())

        mocked_app_options['project_path'] = ""

        _renew_prj_dir(pdv.copy())

        assert not os_path_isdir(os_path_join(project_path, TEMPLATES_FOLDER))

        pdv['project_type'] = ROOT_PRJ
        pdv['namespace_name'] = tst_ns_name

        _renew_prj_dir(pdv.copy())

        assert os_path_isdir(project_path)
        assert not os_path_isdir(os_path_join(project_path, TEMPLATES_FOLDER))
        assert os_path_isdir(os_path_join(package_path, TEMPLATES_FOLDER))

        assert os_path_isdir(os_path_join(project_path, DOCS_FOLDER))
        assert os_path_isdir(os_path_join(project_path, TESTS_FOLDER))
        assert os_path_isfile(os_path_join(project_path, 'main' + PY_EXT))
        assert os_path_isfile(os_path_join(project_path, BUILD_CONFIG_FILE))

        assert not os.path.exists(app_name)  # check that cwd/project_path of this project did not get affected
        assert not os.path.exists(BUILD_CONFIG_FILE)

    def test_renew_project_exits_on_erroneous_pdv_value(self, empty_repo_path, patched_exit_call_wrapper):
        pdv = ProjectDevVars(project_path=empty_repo_path)
        inv_project_type = "any-invalid-or-unknown-project-type"

        calls = patched_exit_call_wrapper(_renew_project, pdv, inv_project_type)

        assert len(calls) == 1
        assert inv_project_type in calls[0][0][1]
        assert "invalid project type" in calls[0][0][1]
        assert calls[0][0][0] == 8         # (8, err code

    def test_renew_project_new_app_from_parent_via_package(self, tmp_path):
        project_name = "tst_app_prj"
        parent_dir = os_path_join(str(tmp_path), DEF_PROJECT_PARENT_FOLDER)
        project_path = norm_path(os_path_join(parent_dir, project_name))
        os.makedirs(parent_dir)

        with in_wd(parent_dir):
            parent_pdv = ProjectDevVars(project_path=project_name)
            assert parent_pdv['project_type'] == NO_PRJ
            assert parent_pdv['project_path'] == os_path_join(norm_path(""), project_name)

            app_pdv = _renew_project(parent_pdv, APP_PRJ)

            assert app_pdv['project_path'] == project_path
            assert app_pdv['project_type'] == APP_PRJ

            assert os_path_isdir(project_path)
            assert os_path_isfile(os_path_join(project_path, 'main' + PY_EXT))
            assert os_path_isfile(os_path_join(project_path, BUILD_CONFIG_FILE))
            assert os_path_isdir(os_path_join(project_path, DOCS_FOLDER))
            assert not os_path_isdir(os_path_join(project_path, TEMPLATES_FOLDER))
            assert os_path_isdir(os_path_join(project_path, TESTS_FOLDER))

    def test_renew_project_new_app_from_parent_via_abs_path(self, mocked_app_options, tmp_path):
        parent_dir = os_path_join(str(tmp_path), DEF_PROJECT_PARENT_FOLDER)
        pkg_name = "tst_app_prj"
        project_path = norm_path(os_path_join(parent_dir, pkg_name))
        mocked_app_options['project_path'] = pkg_name
        os.makedirs(parent_dir)
        pdv = ProjectDevVars(project_path=project_path)

        with in_wd(parent_dir):
            app_pdv = _renew_project(pdv, APP_PRJ)

            assert app_pdv['namespace_name'] == ""
            assert app_pdv['project_type'] == APP_PRJ
            assert app_pdv['project_path'] == project_path
            assert os_path_isdir(project_path)
            assert os_path_isfile(os_path_join(project_path, 'main' + PY_EXT))
            assert os_path_isfile(os_path_join(project_path, BUILD_CONFIG_FILE))
            assert os_path_isdir(os_path_join(project_path, DOCS_FOLDER))
            assert not os_path_isdir(os_path_join(project_path, TEMPLATES_FOLDER))
            assert os_path_isdir(os_path_join(project_path, TESTS_FOLDER))

    def test_renew_project_new_package_from_parent_via_rel_path(self, tmp_path):
        pkg_name = "new_tst_pkg_prj"
        parent_dir = os_path_join(str(tmp_path), DEF_PROJECT_PARENT_FOLDER)
        project_path = norm_path(os_path_join(parent_dir, pkg_name))
        os.makedirs(parent_dir)

        with in_wd(parent_dir):
            new_pdv = ProjectDevVars(main_app_options={'project_path': pkg_name}, project_path=pkg_name)

            new_pdv = _renew_project(new_pdv, PACKAGE_PRJ)

            assert new_pdv['namespace_name'] == ""
            assert new_pdv['project_path'] == project_path
            assert new_pdv['project_type'] == PACKAGE_PRJ

            assert norm_path(pkg_name) == project_path
            assert os_path_isdir(project_path)
            assert os_path_isfile(os_path_join(project_path, pkg_name, PY_INIT))
            assert not os_path_isfile(os_path_join(project_path, BUILD_CONFIG_FILE))
            assert os_path_isdir(os_path_join(project_path, DOCS_FOLDER))
            assert not os_path_isdir(os_path_join(project_path, TEMPLATES_FOLDER))
            assert os_path_isdir(os_path_join(project_path, TESTS_FOLDER))

            assert git_current_branch(project_path).startswith(f"created_new_{PACKAGE_PRJ}_{pkg_name}_")

    def test_wait(self):
        mock_sleep = MagicMock()
        with patch('aedev.project_manager.__main__.time.sleep', new=mock_sleep):
            _wait(ProjectDevVars(**{'main_app_options': {'delay': 3.69}}))
            mock_sleep.assert_called_with(3.69)

        _wait(ProjectDevVars(**{'main_app_options': {'delay': 0}}))


@skip_gitlab_ci  # skip on gitlab because of a missing remote repository user account token
class TestHelpersRemote:
    """ test helper functions that need internet access, some of them need also authentication. """
    def test_guess_next_action(self):
        for project_path in paths_of_test_projects():
            project_name = os_path_basename(project_path)
            git_checkout(project_path, "--detach")

            ret = _guess_next_action(ProjectDevVars(project_path=project_path))

            assert ret.startswith("¡detached HEAD")

            git_checkout(project_path, DEF_MAIN_BRANCH)
            version_file = main_file_path(project_path, itg_projects[project_name]['type'],
                                          namespace_name=itg_ns_name if project_name.startswith(itg_ns_name) else "")
            ver_fil_content = read_file(version_file)
            write_file(version_file, ver_fil_content.replace(VERSION_PREFIX, "any_var = " + VERSION_QUOTE))

            ret = _guess_next_action(ProjectDevVars(project_path=project_path))

            assert ret.startswith("¡empty or invalid project version")

            write_file(version_file, ver_fil_content)

            ret = _guess_next_action(ProjectDevVars(project_path=project_path))

            assert ret == 'renew_project'   # committed version_file restored, working tree is clean / all committed

            write_file(version_file, ver_fil_content + "# test_guess_next_action() added new line\n")

            ret = _guess_next_action(ProjectDevVars(project_path=project_path))

            assert ret.startswith(uncommitted_guess_prefix)

            new_branch = 'new_feature_branch_name_testing_guest_next_action' + now_str(sep="_")
            git_checkout(project_path, new_branch=new_branch)

            ret = _guess_next_action(ProjectDevVars(project_path=project_path))

            assert ret.startswith("¡unstaged files found")

            git_add(project_path)

            ret = _guess_next_action(ProjectDevVars(project_path=project_path))

            assert ret == 'prepare_commit'

            write_file(os_path_join(project_path, COMMIT_MSG_FILE_NAME), "msg without project_version placeholder")

            ret = _guess_next_action(ProjectDevVars(project_path=project_path))

            assert ret == 'prepare_commit'

            write_file(os_path_join(project_path, COMMIT_MSG_FILE_NAME), "test_guest_next_action V {project_version}")

            ret = _guess_next_action(ProjectDevVars(project_path=project_path))

            assert ret == 'commit_project'

            git_commit(project_path, tst_pkg_version)
            git_checkout(project_path, DEF_MAIN_BRANCH)
            git_add(project_path)
            git_commit(project_path, ProjectDevVars(project_path=project_path)['project_version'])

            ret = _guess_next_action(ProjectDevVars(project_path=project_path))

            assert ret == 'renew_project'

            if project_name not in itg_projects:  # exclude itg projects to keep ini/next renew action for further tests
                git_checkout(project_path, new_branch)

                ret = _guess_next_action(ProjectDevVars(project_path=project_path))

                assert ret.startswith(f"¡current branch '{new_branch}' not on remote")

    @skip_if_not_maintainer
    def test_init_act_exec_args_show_remote(self, capsys, mocked_app_options):
        mocked_app_options['action'] = 'show_remote'
        mocked_app_options['arguments'] = ["ae-group/ae_base"]

        mocked_app_options['repo_token'] = "anyInvalidTstToken"

        ini_pdv, act_name, act_args, act_flags = _init_act_exec_args()  # no exit_app but fails on authenticating

        output = capsys.readouterr().out
        assert "401 Unauthorized" in output
        assert " **** connection to gitlab.com remote host server failed" in output

        assert isinstance(ini_pdv, dict)    # ProjectDevVars
        assert act_name == mocked_app_options['action']
        assert act_args == mocked_app_options['arguments']
        assert act_flags == {}
        assert 'host_api' in ini_pdv
        assert isinstance(ini_pdv.pdv_val('host_api'), GitlabCom)
        assert ini_pdv['repo_token'] == mocked_app_options['repo_token']

        mocked_app_options['repo_token'] = itg_mtn_token   # use token from local .env file

        ini_pdv, act_name, act_args, act_flags = _init_act_exec_args()

        assert isinstance(ini_pdv, dict)    # ProjectDevVars
        assert act_name == mocked_app_options['action']
        assert act_args == mocked_app_options['arguments']
        assert act_flags == {}
        assert 'host_api' in ini_pdv
        assert isinstance(ini_pdv.pdv_val('host_api'), GitlabCom)
        assert ini_pdv['repo_token'] == mocked_app_options['repo_token']

        del mocked_app_options['repo_token']

        ini_pdv, act_name, act_args, act_flags = _init_act_exec_args()

        assert isinstance(ini_pdv, dict)    # ProjectDevVars
        assert act_name == mocked_app_options['action']
        assert act_args == mocked_app_options['arguments']
        assert act_flags == {}
        assert 'host_api' in ini_pdv
        assert isinstance(ini_pdv.pdv_val('host_api'), GitlabCom)

    def test_show_status(self, capsys, changed_repo_path, empty_repo_path, mocked_app_options, module_repo_path):
        mocked_app_options['more_verbose'] = False
        test_projects = paths_of_test_projects(changed_repo_path, empty_repo_path, module_repo_path)

        err_prefix = "detected main_branch='develop' with added/changed/uncommitted files: "

        for project_path in test_projects:
            _ensure_tst_ns_portion_version_file(project_path)  # needed for changed/empty, leave itg projects untouched

            _show_status(ProjectDevVars(project_path=project_path))

            output = capsys.readouterr().out
            assert output, f"with {project_path=}"
            assert "-- project vars:" not in output, f"with {project_path=}"
            assert "-- git status:" not in output, f"with {project_path=}"
            if project_path == changed_repo_path:
                assert "*** next action discrepancy:" in output, f"with {project_path=}"
                assert err_prefix + " M " + 'ChangeD.y' + ",  D " + 'deleteD.x' + ", ?? " + 'addEd.ooo' in output
            elif project_path == empty_repo_path:
                assert "*** next action discrepancy:" in output, f"with {project_path=}"
                assert err_prefix + "?? .gitignore" in output, f"with {project_path=}"
            elif project_path == module_repo_path:
                assert "*** next action discrepancy:" in output, f"with {project_path=}"
                assert err_prefix + "?? .gitignore, ?? nsn/" + tst_ns_por_pfx + 'module' + PY_EXT in output
            else:       # itg tst projects
                assert "-- next action guess: renew_project" in output

        pdv = ProjectDevVars(project_path=empty_repo_path)
        pdv['children_project_vars'] = {}
        pdv['namespace_name'] = tst_ns_name
        pdv['project_type'] = ROOT_PRJ
        _ensure_tst_ns_portion_version_file(empty_repo_path)
        assert git_checkout(empty_repo_path, new_branch="tst_branch") == ""

        _show_status(pdv)

        output = capsys.readouterr().out
        assert output
        assert "-- project vars:" not in output
        assert "-- git status:" not in output
        assert "*** next action discrepancy:" in output
        assert "unstaged files found! run git add, or delete them: ?? .gitignore" in output

        git_add(empty_repo_path)

        _show_status(pdv)

        output = capsys.readouterr().out
        assert "-- next action guess:" in output

        mocked_app_options['more_verbose'] = True

        for project_path in test_projects:
            _show_status(ProjectDevVars(project_path=project_path))

            output = capsys.readouterr().out
            assert output, f"with {project_path=}"
            assert "-- project vars:" in output, f"with {project_path=}"
            assert "-- git status:" in output, f"with {project_path=}"
            if project_path == changed_repo_path:
                assert "*** next action discrepancy:" in output, f"with {project_path=}"
                assert err_prefix + " M " + 'ChangeD.y' + ",  D " + 'deleteD.x' + ", ?? " + 'addEd.ooo' in output
            elif project_path == empty_repo_path:
                assert "-- next action guess: prepare_commit" in output, f"with {project_path=}"
            elif project_path == module_repo_path:
                assert "*** next action discrepancy:" in output, f"with {project_path=}"
                assert err_prefix + "?? .gitignore, ?? nsn/" + tst_ns_por_pfx + 'module' + PY_EXT in output
            else:  # itg tst projects
                assert "-- next action guess: renew_project" in output

        pdv = ProjectDevVars(project_path=empty_repo_path)
        pdv['children_project_vars'] = {}
        pdv['namespace_name'] = tst_ns_name
        pdv['project_type'] = ROOT_PRJ
        assert git_checkout(empty_repo_path, new_branch="tst_2nd_branch") == ""
        git_add(empty_repo_path)

        _show_status(pdv)

        output = capsys.readouterr().out
        assert output
        assert "-- project vars:" in output
        assert "-- git status:" in output
        assert "-- next action guess:" in output


@skip_gitlab_ci
@skip_if_no_integration_tests
@skip_if_not_maintainer
class TestIntegration:
    def test_full_git_workflow(self):
        for project_path in paths_of_test_projects():
            assert os_path_isdir(project_path)
            project_name = os_path_basename(project_path)
            project_type = itg_projects[project_name]['type']
            project_role = itg_projects[project_name]['role']
            project_state = itg_projects[project_name]['state']

            pdv = _itg_pdv(project_name, branch=f'test_full_git_workflow_{now_str(sep="_")}')
            old_ver = pdv['project_version']
            pdv['host_api'] = host_api = _remote_connect(pdv, "workflow")  # _guess_next_action() need pdv['host_api']

            pdv = _renew_project(pdv, project_type)

            new_ver = pdv['project_version']
            assert pdv.pdv_val('main_app_options').pop('branch')
            assert new_ver == latest_remote_version(pdv)
            assert _guess_next_action(pdv) == 'prepare_commit'

            write_file(main_file_path(project_path, project_type, namespace_name=pdv['namespace_name']),
                       f"# full git workflow integration test version: {old_ver} -> {new_ver}\n",
                       extra_mode='a')

            prepare_commit(pdv)

            assert os_path_isfile(os_path_join(project_path, COMMIT_MSG_FILE_NAME))
            assert "{project_version}" in read_file(os_path_join(project_path, COMMIT_MSG_FILE_NAME))
            assert git_uncommitted(project_path)
            assert _guess_next_action(pdv) == 'commit_project'

            commit_project(pdv)

            assert "{project_version}" not in read_file(os_path_join(project_path, COMMIT_MSG_FILE_NAME))
            assert not git_uncommitted(project_path)
            assert _guess_next_action(pdv) == 'push_project'

            host_api.push_project(pdv)

            assert _guess_next_action(pdv) == 'request_merge'

            host_api.request_merge(pdv)

            assert _guess_next_action(pdv) == 'release_project'

            if project_role == 'ctb' and project_state == 'forked':  # switch to mtn role to merge MR & for PyPI release
                pdv['repo_user'] = itg_mtn_name
                pdv['repo_token'] = itg_mtn_token
                pdv['host_api'] = host_api = _remote_connect(pdv, "mtn_workflow")

            if project_state == 'forked':
                host_api.merge_pushed_project(pdv)

            assert _guess_next_action(pdv) == 'release_project'

            host_api.release_project(pdv, 'LATEST')

            if pdv['pip_name']:  # empty-pip_name/no-releases for 'ctb'&'cloned', because not having PYPI_PASSWORD in CI
                retries = 69  # int(189.0 / pdv.pdv_val('main_app_options')['delay'])  # retrying/waiting ~3 minutes
                while retries and (cur_ver := get_pypi_versions(pdv['pip_name'], pypi_test=True)[-1]) != new_ver:
                    time.sleep(3)   # _wait(pdv)      # be patient because test.pypi.org is even slower than pypi.org
                    print(f" . .  {retries=} left for PyPI release of {pdv['pip_name']} {new_ver} ({cur_ver=}")
                    retries -= 1
                print(f"!!!!!!{project_name=} full_git_workflow release-check to test.pypi.org with {retries=} left")
                assert retries > 0, f"for {project_name=}"


def test_teardown_cleanup_check_hook():
    """ placeholder for errors detected in teardown_module(). """
