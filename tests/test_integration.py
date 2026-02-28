""" project manager integration tests. only running if the OS/env variable RUN_INTEGRATION_TESTS is set. """
import os
import shutil
import time

from dataclasses import dataclass
from typing import Any

import pytest

from packaging.version import Version

from ae.base import (
    norm_name, norm_path, now_str, on_ci_host,
    os_path_basename, os_path_isdir, os_path_isfile, os_path_join,
    read_file, write_file)
from ae.core import main_app_instance, temp_context_cleanup
from ae.console import ConsoleApp
from ae.shell import debug_or_verbose
from aedev.base import (
    ANY_PRJ_TYPE, COMMIT_MSG_FILE_NAME, DEF_MAIN_BRANCH, MODULE_PRJ, PACKAGE_PRJ,
    TEST_PROJECTS_NAMESPACE, TEST_PROJECTS_PARENT_FOLDER, TEST_PROJECTS_REMOTE, VERSION_PREFIX, VERSION_QUOTE,
    get_pypi_versions)
from aedev.commands import (
    EXEC_GIT_ERR_PREFIX, GIT_CLONE_CACHE_CONTEXT, SHELL_LOG_FILE_NAME_SUFFIX,
    git_add, git_any, git_checkout, git_commit,
    git_uncommitted, in_prj_dir_venv, sh_log, sh_logs)
from aedev.project_vars import (
    ENV_VAR_NAME_PREFIX, PDV_REPO_GROUP_SUFFIX, PDV_REPO_HOST_PROTOCOL, ROOT_PRJ,
    latest_remote_version, main_file_path, ProjectDevVars)

from aedev.project_manager.templates import (
    CACHED_TPL_PROJECTS,
    check_templates, register_template, template_path_option)
from aedev.project_manager.utils import guess_next_action, refresh_pdv

# noinspection PyProtectedMember
from aedev.project_manager.__main__ import (
    REGISTERED_ACTIONS, REGISTERED_HOSTS_CLASS_NAMES, TPL_IMPORT_NAMES,
    _renew_project, _show_status,
    clone_project, commit_project, init_main, prepare_commit)

from tests.conftest import logging_unpatched_shutdown_setup, logging_unpatched_shutdown_teardown, skip_gitlab_ci


from tests.constants_and_fixtures import (
    gitlab_remote, mocked_app_options, pdv_with_email, remote_connect,
    tst_ctb_name, tst_ctb_token, tst_mtn_name, tst_mtn_token,
    tst_namespaces_roots, tst_pkg_version, tst_tpls_register,
    uncommitted_guess_prefix)


# integration tests types, constants and variables

@dataclass
class ItgTstPrj:
    """ integration test project """
    role: str                   # project owner role (maintainer == 'mtn' | contributor == 'ctb')
    state: str                  # download state ('cloned' | 'forked')
    type: str                   # project type (see :data:`~aedev.base.ANY_PRJ_TYPE`)
    is_portion: bool = False    # specify True for namespace portion projects

    @property
    def name(self):
        """ project name (and project root folder name). """
        if self.type == ROOT_PRJ:
            return ITG_ROOT_PRJ_NAME
        return (f"{TEST_PROJECTS_NAMESPACE}_" if self.is_portion else ""
                ) + f"{self.role}_{self.state}_{norm_name(self.type)}_w"

    @property
    def path(self):
        """ local project root path. """
        return os_path_join(ITG_PARENT_PATH, self.name)


ITG_PARENT_PATH = norm_path(os_path_join('~', TEST_PROJECTS_PARENT_FOLDER))
ITG_ROOT_IMPORT_NAME = f'{TEST_PROJECTS_NAMESPACE}.{TEST_PROJECTS_NAMESPACE}'
if tst_ctb_token:
    tst_namespaces_roots.append(ITG_ROOT_IMPORT_NAME)

ITG_ROOT_PRJ_NAME = f'{TEST_PROJECTS_NAMESPACE}_{TEST_PROJECTS_NAMESPACE}'
ITG_ROOT_PRJ_PATH = os_path_join(ITG_PARENT_PATH, ITG_ROOT_PRJ_NAME)

itg_pjm_app: ConsoleApp | None = None

# 1st test prj has to be mtn-cloned ROOT_PRJ to allow update&push of new portion; auto-added to root/dev_req.txt
itg_tst_projects = {
    _prj.name: _prj for _prj in [
        # ItgTstPrj(role='ctb', state='forked', type=ROOT_PRJ),  -- would get overwritten by next line (same dict key)
        ItgTstPrj(role='mtn', state='cloned', type=ROOT_PRJ),
        ItgTstPrj(role='ctb', state='forked', type=MODULE_PRJ, is_portion=True),
        # ItgTstPrj(role='mtn', state='cloned', type=PACKAGE_PRJ, is_portion=True),
        ItgTstPrj(role='ctb', state='forked', type=PACKAGE_PRJ, is_portion=True),
        # ItgTstPrj(role='mtn', state='forked', type=PACKAGE_PRJ, is_portion=True),
    ] + [
        ItgTstPrj(role=('ctb', 'mtn')[int(_idx / 2) % 2], state=('cloned', 'forked')[_idx % 2], type=_prj_type)
        for _idx, _prj_type in enumerate(_ for _ in ANY_PRJ_TYPE if _ != ROOT_PRJ)
    ]
}


# integration tests of this test module have to run one after the other (sequential/serial) on xdist/parallel unit tests
pytestmark = pytest.mark.xdist_group(name="unit_tests_in_this_module_run_serial")


def setup_module():
    """ clone template projects to speedup tests, printing warning messages if the tested module is not set up. """
    print()
    print(f"::::: {os_path_basename(__file__)} setup_module BEG - {main_app_instance()=} {tst_tpls_register=}")

    err = set()
    if not tst_ctb_token or not tst_mtn_token:
        err.add("  ::* missing test-maintainer/contributor credentials")
    if on_ci_host():
        err.add("  :*: tests are running at git remote server")
    if not os.getenv('RUN_INTEGRATION_TESTS'):
        err.add("  *:: RUN_INTEGRATION_TESTS env var is unset")
    global itg_pjm_app
    if itg_pjm_app is not None:  # prevent multiple initialization of integration test env (because of setup_module()
        err.add("  *** setup_module() got called multiple times - check and fix the test setup")
    if err:
        print("***** skipped integration test projects preparation, because of:")
        for msg in err:
            print(msg)
        return  # pytest does call setup_module() again if 1st test setup fails
    # init globals itg_pjm_app and cae (in __main__) in order to use the pjm action-functions/-methods
    itg_pjm_app = init_main()

    # for import_name in tst_namespaces_roots + TPL_IMPORT_NAMES:
    for import_name in TPL_IMPORT_NAMES:
        register_template(import_name, {}, CACHED_TPL_PROJECTS, (), [])

    write_file(norm_path(os_path_join("~", 'git' + SHELL_LOG_FILE_NAME_SUFFIX)),
               f"\n\n{now_str(sep='-')}\n# pjm test suite enabled global git log\n",
               extra_mode='a')  # ensure enabled git logging and add test suite run header marker/comment to log file

    logging_unpatched_shutdown_setup()

    print(f"::::: {os_path_basename(__file__)} setup_module END - {main_app_instance()=} {tst_tpls_register=}")


def teardown_module():
    """ check if the tested module is still set up correctly at the end of this test module. """
    print()
    print(f"::::: {os_path_basename(__file__)} teardown_module BEG - {main_app_instance()=} {tst_tpls_register=}")

    assert not (errors := logging_unpatched_shutdown_teardown()), f"integration test logged {len(errors)} {errors=}"

    CACHED_TPL_PROJECTS.clear()                     # prevent side effects if other module unit tests running after

    temp_context_cleanup()      # cleanup temp dir default and git clone context for other/following test modules
    temp_context_cleanup(GIT_CLONE_CACHE_CONTEXT)

    print(f"::::: {os_path_basename(__file__)} teardown_module END - {main_app_instance()=} {tst_tpls_register=}")


# helpers for the preparation of initial/new and already existing integration test projects ---------------------------


def _itg_download_test_project(itg_test_prj: ItgTstPrj, purpose: str = "") -> tuple[str, str, str]:
    project_path = itg_test_prj.path
    assert not os_path_isdir(project_path)
    project_name = itg_test_prj.name
    project_type = itg_tst_projects[project_name].type
    project_role = itg_tst_projects[project_name].role
    project_state = itg_tst_projects[project_name].state

    _write_pdv_env(project_name)
    assert os_path_isfile(os_path_join(project_path, ".env"))

    pdv = _itg_pdv(project_name)
    if project_state == 'cloned':
        clone_project(pdv, project_name)
    else:
        pdv['host_api'] = host_api = remote_connect(pdv, "fork")
        host_api.fork_project(pdv, TEST_PROJECTS_NAMESPACE + PDV_REPO_GROUP_SUFFIX + '/' + project_name)
    assert os_path_isdir(project_path)

    print(f"  !!! {project_state} {project_role} {purpose} test project {pdv['project_desc']} to {project_path=}")

    return project_name, project_path, project_type


def _itg_pdv(project_name: str, branch: str = '', user_role: str = '') -> ProjectDevVars:
    role = user_role or itg_tst_projects[project_name].role

    pdv_kwargs: dict[str, Any] = {'main_app_options': {'delay': 0.03, 'git_log': True, 'versionIncrementPart': 3},
                                  'project_path': itg_tst_projects[project_name].path,
                                  'project_type': itg_tst_projects[project_name].type,
                                  'AUTHOR': tst_mtn_name if role == 'mtn' else tst_ctb_name,
                                  'repo_user': tst_mtn_name if role == 'mtn' else tst_ctb_name,
                                  'repo_token': tst_mtn_token if role == 'mtn' else tst_ctb_token}

    if branch:
        pdv_kwargs['main_app_options']['branch'] = branch

    if project_name.startswith(TEST_PROJECTS_NAMESPACE + "_"):
        pdv_kwargs['namespace_name'] = TEST_PROJECTS_NAMESPACE
        pdv_kwargs['main_app_options'][template_path_option(ITG_ROOT_IMPORT_NAME)] = ITG_ROOT_PRJ_PATH

    if itg_tst_projects[project_name].role == 'ctb' and itg_tst_projects[project_name].state == 'cloned':
        pdv_kwargs['repo_group'] = tst_ctb_name
        pdv_kwargs['pip_name'] = ""
    else:
        pdv_kwargs['repo_group'] = TEST_PROJECTS_NAMESPACE + PDV_REPO_GROUP_SUFFIX

    pdv = pdv_with_email(**pdv_kwargs)
    return pdv


def _itg_test_project_exists_remotely(remote_url: str) -> bool:
    return not ((out := git_any("..", 'ls-remote', remote_url)) and out and out[0].startswith(EXEC_GIT_ERR_PREFIX))


def _itg_test_projects_parametrize(filter_role: str = '', filter_state: str = '') -> tuple[str, list[ItgTstPrj]]:
    test_projects = [tst_prj for tst_prj in itg_tst_projects.values()
                     if (filter_state == '' or tst_prj.state == filter_state)
                     and (filter_role == '' or tst_prj.role == filter_role)]

    return 'itg_test_prj', test_projects


def _push_to_remote_and_pypi(pdv: ProjectDevVars):
    project_path, project_name = pdv['project_path'], pdv['project_name']

    _refresh_managed_files_from_templates(pdv)
    git_add(project_path)
    prepare_commit(pdv, f"{project_name} created/extended by integration test preparation. V {{project_version}}")
    refresh_pdv(pdv)

    commit_project(pdv)
    refresh_pdv(pdv)

    pdv['host_api'] = host_api = remote_connect(pdv, "push-new-itg-project")
    host_api.push_project(pdv)
    refresh_pdv(pdv)
    host_api.request_merge(pdv)
    refresh_pdv(pdv)
    host_api.release_project(pdv, 'LATEST')
    # refresh_pdv(pdv)

    if pdv['pip_name']:
        retries = 69  # waiting/checking/retrying maximal ~= 6 minutes (test.pypi.org is slow)
        while retries and get_pypi_versions(pdv['pip_name'], pypi_test=True)[-1] != pdv['project_version']:
            print(f"  ... waiting for the test.pypi.org release of the added {project_name} test project; {retries=}")
            time.sleep(6)
            retries -= 1

    print(f"  ^^  {project_path} committed and pushed to origin{' and PyPI' if pdv['pip_name'] else ''}")


def _refresh_managed_files_from_templates(pdv: ProjectDevVars) -> bool:
    project_path = pdv['project_path']

    if not os_path_isdir(project_path):
        return False

    with in_prj_dir_venv(project_path):
        man = check_templates(itg_pjm_app, pdv)
        if not man:
            return False

        if man.missing_files or man.outdated_files:
            man.deploy()
            refresh_pdv(pdv)
            return True

    return False


def _write_pdv_env(project_name: str, user_role: str = ''):
    prj_path = itg_tst_projects[project_name].path
    prj_role = itg_tst_projects[project_name].role
    is_maintainer = (user_role or prj_role) == 'mtn'

    var_names_values = (
        (ENV_VAR_NAME_PREFIX + 'AUTHOR', tst_mtn_name if is_maintainer else tst_ctb_name),
        # (ENV_VAR_NAME_PREFIX + 'AUTHOR_EMAIL', tst_mtn_email if is_mtn else tst_ctb_email),
        (ENV_VAR_NAME_PREFIX + 'repo_user', tst_mtn_name if is_maintainer else tst_ctb_name),
        (ENV_VAR_NAME_PREFIX + 'repo_token', tst_mtn_token if is_maintainer else tst_ctb_token),
    )
    if prj_role == 'ctb' and itg_tst_projects[project_name].state == 'cloned':
        var_names_values += ((ENV_VAR_NAME_PREFIX + 'repo_group', tst_ctb_name),
                             (ENV_VAR_NAME_PREFIX + 'pip_name', '""'))
    elif not project_name.startswith(TEST_PROJECTS_NAMESPACE + "_"):  # is namespace root/portion project
        var_names_values += ((ENV_VAR_NAME_PREFIX + 'repo_group', f'{TEST_PROJECTS_NAMESPACE}{PDV_REPO_GROUP_SUFFIX}'),)

    write_file(os_path_join(prj_path, '.env'),
               f"# auto-generated for {prj_role} user by pjm-test_project_manager tests" + os.linesep +
               os.linesep.join(nam + "=" + val for nam, val in var_names_values) + os.linesep,
               make_dirs=True)

    sh_log(f"# {project_name=} test enabled/extended git log; user role: {user_role or prj_role}",
           log_file_paths=sh_logs(log_enable_dir=prj_path, log_name_prefix='git'))


def test_setup_of_test_constants_and_paths():
    assert REGISTERED_ACTIONS
    assert REGISTERED_HOSTS_CLASS_NAMES
    assert TPL_IMPORT_NAMES

    assert isinstance(CACHED_TPL_PROJECTS, dict)     # empty if running on remote CI

    assert not os_path_isfile(os_path_join(ITG_PARENT_PATH, '.env'))  # ensure gap to prevent bleeding credentials/.env


@skip_gitlab_ci  # skip on gitlab because of a missing remote repository user account token
@pytest.mark.integration
class TestEnvPreparation:
    def test_local_prj_dir_parent(self):
        os.makedirs(ITG_PARENT_PATH, exist_ok=True)
        assert os_path_isdir(ITG_PARENT_PATH)

    @pytest.mark.parametrize(*_itg_test_projects_parametrize(), ids=str)
    def test_local_prj_dir(self, itg_test_prj):
        if os_path_isdir(itg_test_prj.path):
            shutil.rmtree(itg_test_prj.path)     # wipe any rests on local machine from last test run
        assert not os.path.exists(itg_test_prj.path)

    def test_local_prj_dir_parent_is_empty(self):
        assert os.listdir(ITG_PARENT_PATH) == []

    def test_local_namespace_root_cloning_if_exists_on_remote(self):
        # ensure that remotely existing namespace root project get cloned to allow addition of newly added
        # portions via _renew_local_root_req_file()
        url = (f"{PDV_REPO_HOST_PROTOCOL}{TEST_PROJECTS_REMOTE}"
               f"/{TEST_PROJECTS_NAMESPACE}{PDV_REPO_GROUP_SUFFIX}/{ITG_ROOT_PRJ_NAME}.git")
        if not _itg_test_project_exists_remotely(url):
            print("  !#! skipped cloning of namespace root project (because does already not exist at remote)")
            return

        _write_pdv_env(ITG_ROOT_PRJ_NAME)
        assert os_path_isfile(os_path_join(ITG_ROOT_PRJ_PATH, ".env"))

        pdv = _itg_pdv(ITG_ROOT_PRJ_NAME)
        clone_project(pdv, ITG_ROOT_PRJ_NAME)
        assert os_path_isdir(ITG_ROOT_PRJ_PATH)

        print(f"  !!! cloned the namespace root test project ({pdv['project_desc']}) to {ITG_ROOT_PRJ_PATH}")

    @pytest.mark.parametrize(*_itg_test_projects_parametrize(), ids=str)
    def test_local_creation_of_newly_added_test_projects(self, itg_test_prj):
        ctb_project = itg_test_prj.role == 'ctb' and itg_test_prj.state == 'cloned'
        grp_name = tst_ctb_name if ctb_project else f"{TEST_PROJECTS_NAMESPACE}{PDV_REPO_GROUP_SUFFIX}"
        remote_url = f"{PDV_REPO_HOST_PROTOCOL}{TEST_PROJECTS_REMOTE}/{grp_name}/{itg_test_prj.name}.git"
        if _itg_test_project_exists_remotely(remote_url):
            print(f"  !#! skipped creation of test project {itg_test_prj} because exists already at remote")
            return

        adding_role = 'ctb' if ctb_project else 'mtn'
        _write_pdv_env(itg_test_prj.name, user_role=adding_role)
        pdv = _itg_pdv(itg_test_prj.name, user_role=adding_role)
        desc = f"preparing new {itg_test_prj.type} project repository {itg_test_prj.name} for pjm integration tests"
        print(f" .!!. {desc} in {itg_test_prj.path}, to be pushed onto {remote_url=} under the {adding_role=} role")

        pdv.pdv_val('main_app_options')['branch'] = f"{norm_name(desc)}_on_{now_str(sep='_')}"
        pdv = _renew_project(pdv, itg_test_prj.type)
        pdv.pdv_val('main_app_options').pop('branch')
        assert os_path_isdir(itg_test_prj.path)

    @pytest.mark.parametrize(*_itg_test_projects_parametrize(), ids=str)
    def test_release_newly_added_test_and_namespace_root_projects(self, itg_test_prj):
        if not os_path_isdir(itg_test_prj.path):
            print(f"  !#! skipped initial release of test project {itg_test_prj} because exists already on remote")
            return

        ctb_project = itg_test_prj.role == 'ctb' and itg_test_prj.state == 'cloned'
        grp_name = tst_ctb_name if ctb_project else f"{TEST_PROJECTS_NAMESPACE}{PDV_REPO_GROUP_SUFFIX}"
        remote_url = f"{PDV_REPO_HOST_PROTOCOL}{TEST_PROJECTS_REMOTE}/{grp_name}/{itg_test_prj.name}.git"
        if itg_test_prj.name == ITG_ROOT_PRJ_NAME:  # namespace root could exist remotely
            assert itg_test_prj.role == 'mtn' and itg_test_prj.state == 'cloned' and itg_test_prj.type == ROOT_PRJ
            if not (_uncommitted := git_uncommitted(ITG_ROOT_PRJ_PATH)):  # no newly added portions in this test run
                shutil.rmtree(itg_test_prj.path)
                assert not os.path.exists(itg_test_prj.path)
                return
            if _uncommitted != {'dev_requirements.txt'}:
                print(f"    # ignoring {_uncommitted=} mismatch in extended namespace root itg test project")
            pdv = pdv_with_email(main_app_options={'branch': "pjm_itg_tst_portion_added_to_namespace_" + now_str(),
                                                   'delay': 3,  # needed by request_merge()/get_app_option()
                                                   'versionIncrementPart': 3},  # .. by push/get_app_option()
                                 project_path=ITG_ROOT_PRJ_PATH, repo_token=tst_mtn_token)
            pdv = _renew_project(pdv, ROOT_PRJ)
        else:
            assert not _itg_test_project_exists_remotely(remote_url)
            adding_role = 'ctb' if ctb_project else 'mtn'
            pdv = _itg_pdv(itg_test_prj.name, user_role=adding_role)

        _push_to_remote_and_pypi(pdv)
        assert _itg_test_project_exists_remotely(remote_url)

        print(f" !!!! prepared new project {pdv['project_desc']} in {itg_test_prj.path} and pushed onto {remote_url=}")

        shutil.rmtree(itg_test_prj.path)
        assert not os.path.exists(itg_test_prj.path)

    @pytest.mark.parametrize(*_itg_test_projects_parametrize(), ids=str)
    def test_clone_or_fork_of_test_project_to_local_machine(self, itg_test_prj):
        if itg_test_prj.name == ITG_ROOT_PRJ_NAME:
            print(f"  !#! skipped because namespace root project {itg_test_prj.name} got already cloned")
            return
        _itg_download_test_project(itg_test_prj)

    @pytest.mark.parametrize(*_itg_test_projects_parametrize(), ids=str)
    def test_setup_of_test_project_git_state(self, itg_test_prj):
        pdv = pdv_with_email(project_path=itg_test_prj.path)

        assert guess_next_action(pdv) == 'renew_project'

    @pytest.mark.parametrize(*_itg_test_projects_parametrize(), ids=str)
    def test_setup_of_test_project_versions(self, itg_test_prj):
        pdv = pdv_with_email(project_path=itg_test_prj.path)
        prj_version = Version(pdv['project_version'])

        assert Version(latest_remote_version(pdv)) > Version(pdv['NULL_VERSION'])
        assert Version(latest_remote_version(pdv, increment_part=0)) == prj_version

        assert not pdv['pip_name'] or Version(get_pypi_versions(pdv['pip_name'], pypi_test=True)[-1]) == prj_version


@skip_gitlab_ci  # skip on gitlab because of a missing remote repository user account token
@pytest.mark.integration
class TestActionsGitLab:
    @pytest.mark.parametrize(*_itg_test_projects_parametrize(), ids=str)
    def test_show_status(self, itg_test_prj, capsys, gitlab_remote):
        verbose = debug_or_verbose()

        gitlab_remote.show_status(pdv_with_email(project_path=itg_test_prj.path))

        output = capsys.readouterr().out
        assert ("-- project vars:" in output) is verbose
        assert ("-- git status:" in output) is verbose
        assert "-- next action guess: renew_project" in output, f"with {itg_test_prj.path=}"

    @pytest.mark.parametrize(*_itg_test_projects_parametrize(), ids=str)
    def test_show_status_main_branch(self, itg_test_prj, capsys, gitlab_remote):
        verbose = debug_or_verbose()

        gitlab_remote.show_status(pdv_with_email(project_path=itg_test_prj.path))

        output = capsys.readouterr().out
        assert ("-- project vars:" in output) is verbose
        assert ("-- git status:" in output) is verbose
        assert "-- next action guess: renew_project" in output


@skip_gitlab_ci  # skip on gitlab because of a missing remote repository user account token
@pytest.mark.integration
class TestHelpersRemote:
    """ test helper functions that need internet access, some of them need also authentication. """
    @pytest.mark.parametrize(*_itg_test_projects_parametrize(), ids=str)
    def test_guess_next_action(self, itg_test_prj):
        project_name = itg_test_prj.name
        project_path = itg_test_prj.path
        namespace_name = project_name.startswith(TEST_PROJECTS_NAMESPACE) and TEST_PROJECTS_NAMESPACE or ""
        git_checkout(project_path, "--detach")

        ret = guess_next_action(pdv_with_email(project_path=project_path))

        assert ret.startswith("¡detached HEAD")

        git_checkout(project_path, DEF_MAIN_BRANCH)
        version_file = main_file_path(project_path, itg_tst_projects[project_name].type, namespace_name=namespace_name)
        ver_fil_content = read_file(version_file)
        write_file(version_file, ver_fil_content.replace(VERSION_PREFIX, "any_var = " + VERSION_QUOTE))

        ret = guess_next_action(pdv_with_email(project_path=project_path))

        assert ret.startswith("¡empty or invalid project version")

        write_file(version_file, ver_fil_content)

        ret = guess_next_action(pdv_with_email(project_path=project_path))

        assert ret == 'renew_project'   # committed version_file restored, working tree is clean / all committed

        write_file(version_file, ver_fil_content + "# test_guess_next_action() added new line\n")

        ret = guess_next_action(pdv_with_email(project_path=project_path))

        assert ret.startswith(uncommitted_guess_prefix)

        new_branch = 'new_feature_branch_name_testing_guest_next_action' + now_str(sep="_")
        git_checkout(project_path, new_branch=new_branch)

        ret = guess_next_action(pdv_with_email(project_path=project_path))

        assert ret.startswith("¡unstaged files found")

        git_add(project_path)

        ret = guess_next_action(pdv_with_email(project_path=project_path))

        assert ret == 'prepare_commit'

        write_file(os_path_join(project_path, COMMIT_MSG_FILE_NAME), "msg without project_version placeholder")

        ret = guess_next_action(pdv_with_email(project_path=project_path))

        assert ret == 'prepare_commit'

        write_file(os_path_join(project_path, COMMIT_MSG_FILE_NAME), "test_guest_next_action V {project_version}")

        ret = guess_next_action(pdv_with_email(project_path=project_path))

        assert ret == 'commit_project'

        git_commit(project_path, tst_pkg_version)
        git_checkout(project_path, DEF_MAIN_BRANCH)
        git_add(project_path)
        git_commit(project_path, pdv_with_email(project_path=project_path)['project_version'])

        ret = guess_next_action(pdv_with_email(project_path=project_path))

        assert ret == 'renew_project'

    @pytest.mark.parametrize(*_itg_test_projects_parametrize(), ids=str)
    def test_show_status(self, itg_test_prj, capsys, mocked_app_options):
        mocked_app_options['more_verbose'] = False
        project_path = itg_test_prj.path

        _show_status(pdv_with_email(project_path=project_path))

        output = capsys.readouterr().out
        assert output, f"with {project_path=}"
        assert "-- project vars:" not in output, f"with {project_path=}"
        assert "-- git status:" not in output, f"with {project_path=}"
        assert "-- next action guess: renew_project" in output

        mocked_app_options['more_verbose'] = True

        _show_status(pdv_with_email(project_path=project_path))

        output = capsys.readouterr().out
        assert output, f"with {project_path=}"
        assert "-- project vars:" in output, f"with {project_path=}"
        assert "-- git status:" in output, f"with {project_path=}"
        assert "-- next action guess: renew_project" in output


@skip_gitlab_ci
@pytest.mark.integration
class TestFullWorkflows:
    @pytest.mark.parametrize(*_itg_test_projects_parametrize(), ids=str)
    def test_archive_itg_test_projects_to_prepare_work_flow_tests(self, itg_test_prj):
        print(" !!!  archive integration test projects to prepare full work flow tests")
        assert os_path_isdir(itg_test_prj.path)

        os.rename(itg_test_prj.path, itg_test_prj.path + "_" + now_str())
        assert not os_path_isdir(itg_test_prj.path)

    @pytest.mark.parametrize(*_itg_test_projects_parametrize(filter_role='mtn', filter_state='cloned'), ids=str)
    def test_mtn_cloned_workflow(self, itg_test_prj):
        project_name, project_path, project_type = _itg_download_test_project(itg_test_prj, purpose="workflow")
        pdv = _itg_pdv(project_name, branch=f'test_full_git_workflow_{now_str(sep="_")}')
        old_ver = pdv['project_version']
        pdv['host_api'] = host_api = remote_connect(pdv, "workflow")  # guess_next_action() need pdv['host_api']

        pdv = _renew_project(pdv, project_type)

        new_ver = pdv['project_version']
        assert pdv.pdv_val('main_app_options').pop('branch')
        assert new_ver == latest_remote_version(pdv)
        assert guess_next_action(pdv) == 'prepare_commit'

        write_file(main_file_path(project_path, project_type, namespace_name=pdv['namespace_name']),
                   f"# full git workflow integration test version: {old_ver} -> {new_ver}\n",
                   extra_mode='a')

        prepare_commit(pdv)

        assert os_path_isfile(os_path_join(project_path, COMMIT_MSG_FILE_NAME))
        assert "{project_version}" in read_file(os_path_join(project_path, COMMIT_MSG_FILE_NAME))
        assert git_uncommitted(project_path)
        assert guess_next_action(pdv) == 'commit_project'

        commit_project(pdv)

        assert "{project_version}" not in read_file(os_path_join(project_path, COMMIT_MSG_FILE_NAME))
        assert not git_uncommitted(project_path)
        assert guess_next_action(pdv) == 'push_project'

        host_api.push_project(pdv)

        assert guess_next_action(pdv) == 'request_merge'

        host_api.request_merge(pdv)

        assert guess_next_action(pdv) == 'release_project'

        if itg_test_prj.role == 'ctb' and itg_test_prj.state == 'forked':
            pdv['repo_user'] = tst_mtn_name     # switch to mtn role to merge MR & for PyPI release
            pdv['repo_token'] = tst_mtn_token
            pdv['host_api'] = host_api = remote_connect(pdv, "mtn_workflow")

        if itg_test_prj.state == 'forked':
            host_api.merge_pushed_project(pdv)

        assert guess_next_action(pdv) == 'release_project'

        host_api.release_project(pdv, 'LATEST')

        if pdv['pip_name']:  # empty-pip_name/no-releases for 'ctb'&'cloned', because not having PYPI_PASSWORD in CI
            retries = 69  # int(189.0 / pdv.pdv_val('main_app_options')['delay'])  # retrying/waiting ~3 minutes
            while retries and (cur_ver := get_pypi_versions(pdv['pip_name'], pypi_test=True)[-1]) != new_ver:
                time.sleep(3)   # _wait(pdv)      # be patient because test.pypi.org is even slower than pypi.org
                print(f" . .  {retries=} left for PyPI release of {pdv['pip_name']} {new_ver} ({cur_ver=}")
                retries -= 1
            print(f"!!!!!!{project_name=} full_git_workflow release-check to test.pypi.org with {retries=} left")
            assert retries > 0


def test_if_previous_tests_did_unpatched_call_of_app_shutdown_detected_in_teardown_module():
    pass
