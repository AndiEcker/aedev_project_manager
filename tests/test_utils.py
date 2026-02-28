""" utils module tests. """
import os
from typing import OrderedDict

from unittest.mock import MagicMock, patch

import pytest

from ae.base import in_wd, norm_name, now_str, os_path_dirname, os_path_isfile, os_path_join, read_file, write_file
from ae.shell import STDERR_BEG_MARKER, STDERR_END_MARKER
from ae.managed_files import REFRESHABLE_TEMPLATE_MARKER
from aedev.base import COMMIT_MSG_FILE_NAME, DEF_MAIN_BRANCH, MODULE_PRJ, NO_PRJ, PARENT_PRJ, PIP_CMD, ROOT_PRJ
from aedev.commands import GIT_REMOTE_ORIGIN, GIT_REMOTE_UPSTREAM, git_add, git_checkout, git_commit, git_current_branch
from aedev.project_vars import (
    ENV_VAR_NAME_PREFIX, PDV_REPO_GROUP_SUFFIX, PDV_REPO_HOST_PROTOCOL, PDV_REQ_FILE_NAME,
    ProjectDevVars, frozen_req_file_path)

from constants_and_fixtures import (
    empty_repo_path, ensure_tst_ns_portion_version_file, mocked_app_options, module_repo_path, pdv_with_email,
    tst_ns_name, tst_pkg_version, uncommitted_guess_prefix)

from aedev.project_manager.utils import (
    EXEC_GIT_ERR_PREFIX, PIP_FREEZE_COMMENT,
    children_desc, children_project_names, expected_args, get_app_option, get_branch, get_host_class_name,
    get_host_config_val, get_host_domain, get_host_group, get_host_user_name, get_host_user_token, get_mirror_urls,
    git_init_add, git_push_url, guess_next_action, ppp, project_topics, refresh_pdv,
    update_frozen_req_file, update_frozen_req_files, write_commit_message)


ERR_PREFIX = "¡"
FEATURE_BRANCH = "feature/test"
PORTION_NAME = "portion_name"
PRJ_NAMESPACE = "test"
PRJ_NAME = f"{PRJ_NAMESPACE}_{PORTION_NAME}"
PRJ_ROOT_PATH = f"/{PRJ_NAME}"
PRJ_VERSION = "1.2.3"
PRJ_VERSION_V2 = "2.0.0"

EDITABLE_LINE = f"-e git+https://github.com/org/{PRJ_NAME}.git@abc123#egg={PRJ_NAME}"
FROZEN_FILE_PATH = f"{PRJ_ROOT_PATH}/requirements.frozen.txt"

REQ_FILE_PACKAGES = ["any_package==3.2.1", "other_pkg==6.9", "addPkg==2024.1.0"]
REQ_FILE_PATH = f"{PRJ_ROOT_PATH}/{PDV_REQ_FILE_NAME}"
REQ_FILE_CONTENT = os.linesep.join(REQ_FILE_PACKAGES)


def standard_pdv(**overrides):
    """ ProjectDevVars mock with standard test values. """
    data = {
        'COMMIT_MSG_FILE_NAME': COMMIT_MSG_FILE_NAME,
        'MAIN_BRANCH': DEF_MAIN_BRANCH,
        'REMOTE_ORIGIN': GIT_REMOTE_ORIGIN,
        'REMOTE_UPSTREAM': GIT_REMOTE_UPSTREAM,
        'REPO_HOST_PROTOCOL': PDV_REPO_HOST_PROTOCOL,
        'host_api': MagicMock(),
        'namespace_name': PRJ_NAMESPACE,
        'portion_name': PORTION_NAME,
        'project_name': PRJ_NAME,
        'project_path': PRJ_ROOT_PATH,
        'project_type': NO_PRJ,
        'project_version': PRJ_VERSION,
        'remote_urls': [GIT_REMOTE_ORIGIN, GIT_REMOTE_UPSTREAM],
        'version_file': 'VERSION.txt',
        **overrides
    }
    pdv = MagicMock()
    pdv.__getitem__.side_effect = pdv.pdv_val.side_effect = lambda key: data.get(key, "")

    return pdv


@pytest.fixture
def mock_pdv(request):
    return standard_pdv(**getattr(request, 'param', {}))


@pytest.fixture
def pdv_factory():
    def _factory(overrides):
        return standard_pdv(**overrides)

    return _factory


class TestGuessNextAction:
    @patch('aedev.project_manager.utils.os_path_isfile')
    @patch('aedev.project_manager.utils.read_file')
    @patch('aedev.project_manager.utils.git_any')
    @patch('aedev.project_manager.utils.git_status')
    @patch('aedev.project_manager.utils.git_current_branch')
    @patch('aedev.project_manager.utils.os_path_isdir')
    @patch('aedev.project_manager.utils.latest_remote_version')
    def test_commit_project(self, mock_remote_ver, mock_isdir, mock_branch, mock_status, mock_git_any, mock_read,
                            mock_isfile, mock_pdv):
        mock_isdir.return_value = True
        mock_branch.return_value = FEATURE_BRANCH
        mock_remote_ver.return_value = PRJ_VERSION
        mock_status.return_value = ['file.txt']
        mock_git_any.return_value = [f"{EXEC_GIT_ERR_PREFIX} Exit Code 1"]
        mock_isfile.return_value = True
        mock_read.return_value = "Release {project_version}"

        assert guess_next_action(mock_pdv) == 'commit_project'

    @patch('aedev.project_manager.utils.git_current_branch')
    @patch('aedev.project_manager.utils.os_path_isdir')
    def test_detached_head(self, mock_isdir, mock_branch, mock_pdv):
        mock_isdir.return_value = True
        mock_branch.return_value = None

        result = guess_next_action(mock_pdv)
        assert result.startswith(f"{ERR_PREFIX}detached HEAD!")

    @patch('aedev.project_manager.utils.git_tag_remotes')
    @patch('aedev.project_manager.utils.git_branch_remotes')
    @patch('aedev.project_manager.utils.git_status')
    @patch('aedev.project_manager.utils.git_current_branch')
    @patch('aedev.project_manager.utils.os_path_isdir')
    @patch('aedev.project_manager.utils.latest_remote_version')
    def test_git_workflow_completed(self, mock_remote_ver, mock_isdir, mock_branch, mock_status, mock_branch_remotes,
                                    mock_tag_remotes, mock_pdv):
        mock_isdir.return_value = True
        mock_branch.return_value = FEATURE_BRANCH
        mock_remote_ver.return_value = PRJ_VERSION
        mock_status.return_value = []
        mock_branch_remotes.side_effect = [[GIT_REMOTE_ORIGIN], [GIT_REMOTE_ORIGIN]]
        mock_tag_remotes.return_value = [GIT_REMOTE_ORIGIN]

        result = guess_next_action(mock_pdv)
        assert "workflow fully completed" in result

    @patch('aedev.project_manager.utils.git_current_branch')
    @patch('aedev.project_manager.utils.os_path_isdir')
    def test_invalid_version(self, mock_isdir, mock_branch, mock_pdv):
        mock_isdir.return_value = True
        mock_branch.return_value = DEF_MAIN_BRANCH
        mock_pdv.__getitem__.side_effect = lambda key: "invalid-semver" if key == 'project_version' else DEF_MAIN_BRANCH

        result = guess_next_action(mock_pdv)
        assert "empty or invalid project version" in result

    @patch('aedev.project_manager.utils.git_tag_remotes')
    @patch('aedev.project_manager.utils.git_branch_remotes')
    @patch('aedev.project_manager.utils.git_status')
    @patch('aedev.project_manager.utils.git_current_branch')
    @patch('aedev.project_manager.utils.os_path_isdir')
    @patch('aedev.project_manager.utils.latest_remote_version')
    def test_multiple_merge_requests(self, mock_remote_ver, mock_isdir, mock_branch, mock_status, mock_branch_remotes,
                                     mock_tag_remotes, mock_pdv):
        mock_isdir.return_value = True
        mock_branch.return_value = FEATURE_BRANCH
        mock_remote_ver.return_value = PRJ_VERSION
        mock_status.return_value = []
        mock_branch_remotes.side_effect = [[GIT_REMOTE_ORIGIN], []]  # 2 calls: branch_remotes, release_remotes
        mock_tag_remotes.return_value = [GIT_REMOTE_ORIGIN]

        pdv_data = {
            'project_path': PRJ_ROOT_PATH,
            'project_version': PRJ_VERSION,
            'REMOTE_ORIGIN': GIT_REMOTE_ORIGIN,
            'REMOTE_UPSTREAM': GIT_REMOTE_UPSTREAM,
            'MAIN_BRANCH': DEF_MAIN_BRANCH,
        }
        mock_pdv.__getitem__.side_effect = pdv_data.get

        def pdv_val_side_effect(key):
            if key == 'remote_urls':
                return [GIT_REMOTE_ORIGIN, GIT_REMOTE_UPSTREAM]
            if key == 'host_api':
                return mock_api
            return MagicMock()

        mock_api = MagicMock()
        mock_api.branch_merge_requests.return_value = ['mr1', 'mr2']
        mock_pdv.pdv_val.side_effect = pdv_val_side_effect

        assert "multiple merge requests found" in guess_next_action(mock_pdv)

    @patch('aedev.project_manager.utils.os_path_isdir')
    def test_no_git_repo(self, mock_isdir, mock_pdv):
        """ Tests error message when no Git repository is found. """
        mock_isdir.return_value = False

        result = guess_next_action(mock_pdv)
        assert "no git repository found" in result

    @patch('aedev.project_manager.utils.git_status')
    @patch('aedev.project_manager.utils.git_current_branch')
    @patch('aedev.project_manager.utils.os_path_isdir')
    @patch('aedev.project_manager.utils.latest_remote_version')
    def test_on_main_with_uncommitted(self, mock_remote_ver, mock_isdir, mock_branch, mock_status, mock_pdv):
        mock_isdir.return_value = True
        mock_branch.return_value = DEF_MAIN_BRANCH
        mock_remote_ver.return_value = PRJ_VERSION
        mock_status.return_value = ['file.txt']

        result = guess_next_action(mock_pdv)
        assert "added/changed/uncommitted files" in result

    @patch('aedev.project_manager.utils.git_tag_remotes')
    @patch('aedev.project_manager.utils.git_branch_remotes')
    @patch('aedev.project_manager.utils.git_status')
    @patch('aedev.project_manager.utils.git_current_branch')
    @patch('aedev.project_manager.utils.os_path_isdir')
    @patch('aedev.project_manager.utils.latest_remote_version')
    def test_origin_missing_tag(self, mock_remote_ver, mock_isdir, mock_branch, mock_status, mock_branch_remotes,
                                mock_tag_remotes, mock_pdv):
        mock_isdir.return_value = True
        mock_branch.return_value = FEATURE_BRANCH
        mock_remote_ver.return_value = PRJ_VERSION
        mock_status.return_value = []
        mock_branch_remotes.side_effect = [[GIT_REMOTE_ORIGIN], []]
        mock_tag_remotes.return_value = ['other_remote']  # origin is missing

        result = guess_next_action(mock_pdv)
        assert f"has no project_version='{PRJ_VERSION}' tag" in result

    @patch('aedev.project_manager.utils.os_path_isfile')
    @patch('aedev.project_manager.utils.git_any')
    @patch('aedev.project_manager.utils.git_status')
    @patch('aedev.project_manager.utils.git_current_branch')
    @patch('aedev.project_manager.utils.os_path_isdir')
    @patch('aedev.project_manager.utils.latest_remote_version')
    def test_prepare_commit(self, mock_remote_ver, mock_isdir, mock_branch, mock_status, mock_git_any, mock_isfile,
                            mock_pdv):
        mock_isdir.return_value = True
        mock_branch.return_value = FEATURE_BRANCH
        mock_remote_ver.return_value = PRJ_VERSION
        mock_status.return_value = ['file.txt']
        mock_git_any.return_value = [f"{EXEC_GIT_ERR_PREFIX}1"]
        mock_isfile.return_value = False

        assert guess_next_action(mock_pdv) == 'prepare_commit'

    @patch('aedev.project_manager.utils.git_tag_remotes')  # patched to prevent FileNotFoundError/chdir
    @patch('aedev.project_manager.utils.git_branch_remotes')
    @patch('aedev.project_manager.utils.git_status')
    @patch('aedev.project_manager.utils.git_current_branch')
    @patch('aedev.project_manager.utils.os_path_isdir')
    @patch('aedev.project_manager.utils.latest_remote_version')
    def test_push_project(self, mock_remote_ver, mock_isdir, mock_branch, mock_status, mock_branch_remotes,
                          mock_tag_remotes, mock_pdv):
        mock_isdir.return_value = True
        mock_branch.return_value = FEATURE_BRANCH
        mock_remote_ver.return_value = PRJ_VERSION
        mock_status.return_value = []
        mock_branch_remotes.return_value = []
        mock_tag_remotes.return_value = []

        assert guess_next_action(mock_pdv) == 'push_project'

    @patch('aedev.project_manager.utils.git_tag_remotes')
    @patch('aedev.project_manager.utils.git_branch_remotes')
    @patch('aedev.project_manager.utils.git_status')
    @patch('aedev.project_manager.utils.git_current_branch')
    @patch('aedev.project_manager.utils.os_path_isdir')
    @patch('aedev.project_manager.utils.latest_remote_version')
    def test_release_project(self, mock_remote_ver, mock_isdir, mock_branch, mock_status, mock_branch_remotes,
                             mock_tag_remotes, mock_pdv):
        mock_isdir.return_value = True
        mock_branch.return_value = FEATURE_BRANCH
        mock_remote_ver.return_value = PRJ_VERSION
        mock_status.return_value = []
        mock_branch_remotes.side_effect = [[GIT_REMOTE_ORIGIN], []]
        mock_tag_remotes.return_value = [GIT_REMOTE_ORIGIN]

        mock_api = mock_pdv.pdv_val('host_api')
        mock_api.branch_merge_requests.return_value = ['mr1']

        assert guess_next_action(mock_pdv) == 'release_project'

    @patch('aedev.project_manager.utils.git_tag_remotes')
    @patch('aedev.project_manager.utils.git_branch_remotes')
    @patch('aedev.project_manager.utils.git_status')
    @patch('aedev.project_manager.utils.git_current_branch')
    @patch('aedev.project_manager.utils.os_path_isdir')
    @patch('aedev.project_manager.utils.latest_remote_version')
    def test_release_remotes_mismatch(self, mock_remote_ver, mock_isdir, mock_branch, mock_status, mock_branch_remotes,
                                      mock_tag_remotes, mock_pdv):
        mock_isdir.return_value = True
        mock_branch.return_value = FEATURE_BRANCH
        mock_remote_ver.return_value = PRJ_VERSION
        mock_status.return_value = []
        mock_branch_remotes.side_effect = [[GIT_REMOTE_ORIGIN], ['extra_remote']]  # release_remotes has 'extra_remote'
        mock_tag_remotes.return_value = [GIT_REMOTE_ORIGIN]

        assert "release remotes ['extra_remote'] are not in version_remotes" in guess_next_action(mock_pdv)

    @patch('aedev.project_manager.utils.git_status')
    @patch('aedev.project_manager.utils.git_current_branch')
    @patch('aedev.project_manager.utils.os_path_isdir')
    @patch('aedev.project_manager.utils.latest_remote_version')
    def test_renew_project(self, mock_remote_ver, mock_isdir, mock_branch, mock_status, mock_pdv):
        """ Tests if 'renew_project' is returned on main branch with no uncommitted changes. """
        mock_isdir.side_effect = [True, True]
        mock_branch.return_value = DEF_MAIN_BRANCH
        mock_remote_ver.return_value = PRJ_VERSION
        mock_status.return_value = []

        assert guess_next_action(mock_pdv) == 'renew_project'

    @patch('aedev.project_manager.utils.git_tag_remotes')
    @patch('aedev.project_manager.utils.git_branch_remotes')
    @patch('aedev.project_manager.utils.git_status')
    @patch('aedev.project_manager.utils.git_current_branch')
    @patch('aedev.project_manager.utils.os_path_isdir')
    @patch('aedev.project_manager.utils.latest_remote_version')
    def test_request_merge(self, mock_remote_ver, mock_isdir, mock_branch, mock_status, mock_branch_remotes,
                           mock_tag_remotes, mock_pdv):
        mock_isdir.return_value = True
        mock_branch.return_value = FEATURE_BRANCH
        mock_remote_ver.return_value = PRJ_VERSION
        mock_status.return_value = []
        mock_branch_remotes.side_effect = [[GIT_REMOTE_ORIGIN], []]
        mock_tag_remotes.return_value = [GIT_REMOTE_ORIGIN]

        pdv_data = {
            'project_path': PRJ_ROOT_PATH,
            'project_version': PRJ_VERSION,
            'REMOTE_ORIGIN': GIT_REMOTE_ORIGIN,
            'REMOTE_UPSTREAM': GIT_REMOTE_UPSTREAM,
            'MAIN_BRANCH': DEF_MAIN_BRANCH
        }
        mock_pdv.__getitem__.side_effect = pdv_data.get

        mock_api = MagicMock()
        mock_api.branch_merge_requests.return_value = []

        def pdv_val_side_effect(key):
            if key == 'remote_urls':
                return [GIT_REMOTE_ORIGIN]
            if key == 'host_api':
                return mock_api
            return MagicMock()

        mock_pdv.pdv_val.side_effect = pdv_val_side_effect

        assert guess_next_action(mock_pdv) == 'request_merge'

    @patch('aedev.project_manager.utils.git_any')
    @patch('aedev.project_manager.utils.git_status')
    @patch('aedev.project_manager.utils.git_current_branch')
    @patch('aedev.project_manager.utils.os_path_isdir')
    @patch('aedev.project_manager.utils.latest_remote_version')
    def test_unstaged_files(self, mock_remote_ver, mock_isdir, mock_branch, mock_status, mock_git_any, mock_pdv):
        mock_isdir.return_value = True
        mock_branch.return_value = FEATURE_BRANCH
        mock_remote_ver.return_value = PRJ_VERSION
        mock_status.return_value = ['file.txt']
        mock_git_any.return_value = []  # no diff output for staged files

        assert "unstaged files found!" in guess_next_action(mock_pdv)

    @patch('aedev.project_manager.utils.increment_version')
    @patch('aedev.project_manager.utils.git_current_branch')
    @patch('aedev.project_manager.utils.os_path_isdir')
    @patch('aedev.project_manager.utils.latest_remote_version')
    def test_version_discrepancy_greater(self, mock_remote_ver, mock_isdir, mock_branch, mock_inc, mock_pdv):
        mock_isdir.return_value = True
        mock_branch.return_value = DEF_MAIN_BRANCH
        mock_remote_ver.return_value = "1.0.0"
        mock_inc.return_value = "1.1.0"
        mock_pdv.__getitem__.side_effect = lambda key: PRJ_VERSION_V2 if key == 'project_version' else DEF_MAIN_BRANCH

        assert f"local project_version='{PRJ_VERSION_V2}' is greater than" in guess_next_action(mock_pdv)

    @patch('aedev.project_manager.utils.git_current_branch')
    @patch('aedev.project_manager.utils.os_path_isdir')
    @patch('aedev.project_manager.utils.latest_remote_version')
    def test_version_discrepancy_less(self, mock_remote_ver, mock_isdir, mock_branch, mock_pdv):
        mock_isdir.return_value = True
        mock_branch.return_value = DEF_MAIN_BRANCH
        mock_remote_ver.return_value = PRJ_VERSION_V2
        mock_pdv.__getitem__.side_effect = lambda key: PRJ_VERSION if key == 'project_version' else DEF_MAIN_BRANCH

        assert f"local project_version='{PRJ_VERSION}' is less than" in guess_next_action(mock_pdv)

    @patch('aedev.project_manager.utils.git_branch_remotes')
    @patch('aedev.project_manager.utils.git_status')
    @patch('aedev.project_manager.utils.git_current_branch')
    @patch('aedev.project_manager.utils.os_path_isdir')
    @patch('aedev.project_manager.utils.latest_remote_version')
    def test_version_not_pushed(self, mock_remote_ver, mock_isdir, mock_branch, mock_status, mock_branch_remotes,
                                mock_pdv):
        mock_isdir.return_value = True
        mock_branch.return_value = FEATURE_BRANCH
        mock_remote_ver.return_value = PRJ_VERSION
        mock_status.return_value = []
        mock_branch_remotes.side_effect = [[GIT_REMOTE_ORIGIN], []]

        with patch('aedev.project_manager.utils.git_tag_remotes') as mock_tag:
            mock_tag.return_value = []
            result = guess_next_action(mock_pdv)
            assert "got not pushed to any remote" in result

    @patch('aedev.project_manager.utils.git_branch_remotes')
    @patch('aedev.project_manager.utils.git_status')
    @patch('aedev.project_manager.utils.git_current_branch')
    @patch('aedev.project_manager.utils.os_path_isdir')
    @patch('aedev.project_manager.utils.latest_remote_version')
    def test_version_remote_mismatch_during_push_check(self, mock_remote_ver, mock_isdir, mock_branch, mock_status,
                                                       mock_branch_remotes, mock_pdv):
        mock_isdir.return_value = True
        mock_branch.return_value = FEATURE_BRANCH
        mock_remote_ver.return_value = PRJ_VERSION
        mock_status.return_value = []
        mock_branch_remotes.return_value = []

        with patch('aedev.project_manager.utils.git_tag_remotes') as mock_tag:
            mock_tag.return_value = [GIT_REMOTE_ORIGIN]
            result = guess_next_action(mock_pdv)
            assert f"current branch '{FEATURE_BRANCH}' not on remotes, although" in result


class TestUpdateFrozenReqFile:
    PIP_WARNING = "WARNING: package xyz not found"

    @pytest.fixture
    def mock_frozen_path_valid(self):
        """ patch frozen_req_file_path() to return a valid frozen file path. """
        with patch('aedev.project_manager.utils.frozen_req_file_path', return_value=FROZEN_FILE_PATH) as mock:
            yield mock

    @pytest.fixture
    def mock_frozen_path_none(self):
        """ patch frozen_req_file_path() to return a falsy value (no frozen file). """
        with patch('aedev.project_manager.utils.frozen_req_file_path', return_value=None) as mock:
            yield mock

    @pytest.fixture
    def mock_read_file(self):
        """ patch read_file() to return the standard fake requirements content. """
        with patch('aedev.project_manager.utils.read_file', return_value=REQ_FILE_CONTENT) as mock:
            yield mock

    @pytest.fixture
    def mock_write_file(self):
        """ patch write_file() so no real file I/O occurs. """
        with patch('aedev.project_manager.utils.write_file') as mock:
            yield mock

    @pytest.fixture
    def mock_sh_exit_no_errors(self):
        """ patch sh_exit_if_exec_err appending clean pip-freeze output to lines_output without any STDERR markers. """
        # noinspection PyUnusedLocal
        def _side_effect(exit_code, cmd, extra_args, lines_output):
            lines_output.extend(REQ_FILE_PACKAGES)

        with patch('aedev.project_manager.utils.sh_exit_if_exec_err', side_effect=_side_effect) as mock:
            yield mock

    @pytest.fixture
    def mock_sh_exit_with_stderr_errors(self):
        """ patch sh_exit_if_exec_err to produce output that contains STDERR markers and at least one error message. """

        # noinspection PyUnusedLocal
        def _side_effect(exit_code, cmd, extra_args, lines_output):
            lines_output.extend([REQ_FILE_PACKAGES[0],
                                 STDERR_BEG_MARKER,
                                 TestUpdateFrozenReqFile.PIP_WARNING,
                                 STDERR_END_MARKER])

        with patch('aedev.project_manager.utils.sh_exit_if_exec_err', side_effect=_side_effect) as mock:
            yield mock

    @pytest.fixture
    def mock_sh_exit_with_stderr_no_error_messages(self):
        """ patch sh_exit_if_exec_err() to produce output with no error messages between the markers. """
        lines = [
            REQ_FILE_PACKAGES[0],
            STDERR_BEG_MARKER,
            STDERR_END_MARKER,
        ]

        # noinspection PyUnusedLocal
        def _side_effect(exit_code, cmd, extra_args, lines_output):
            lines_output.extend(lines)

        with patch('aedev.project_manager.utils.sh_exit_if_exec_err', side_effect=_side_effect) as mock:
            yield mock

    @pytest.fixture
    def mock_project_dev_vars(self):
        """ patch ProjectDevVars to return a mock object that yields PRJ_VERSION. """
        mock_pdv = MagicMock()
        mock_pdv.__getitem__ = MagicMock(return_value=PRJ_VERSION)
        with patch('aedev.project_manager.utils.ProjectDevVars', return_value=mock_pdv) as mock_cls:
            yield mock_cls, mock_pdv

    # tests for update_frozen_req_file() ---------------------------------------------------------------

    def test_all_packages_false_pip_comment_is_removed(self, mock_frozen_path_valid, mock_read_file, mock_write_file):
        lines_with_pip_comment = REQ_FILE_PACKAGES + [
            PIP_FREEZE_COMMENT,
            REQ_FILE_PACKAGES[2],
        ]

        # noinspection PyUnusedLocal
        def _side_effect(exit_code, cmd, extra_args, lines_output):
            lines_output.extend(lines_with_pip_comment)

        with patch('aedev.project_manager.utils.sh_exit_if_exec_err', side_effect=_side_effect):
            errors = update_frozen_req_file(REQ_FILE_PATH, all_packages=False)

        assert errors == []
        written_content = mock_write_file.call_args[0][1]
        assert PIP_FREEZE_COMMENT not in written_content

    def test_all_packages_true_includes_extra_pip_lines(self, mock_frozen_path_valid, mock_read_file, mock_write_file):
        all_lines = REQ_FILE_PACKAGES + [
            PIP_FREEZE_COMMENT,
            REQ_FILE_PACKAGES[2],  # extra line added by pip freeze
        ]

        # noinspection PyUnusedLocal
        def _side_effect(exit_code, cmd, extra_args, lines_output):
            lines_output.extend(all_lines)

        with patch('aedev.project_manager.utils.sh_exit_if_exec_err', side_effect=_side_effect):
            errors = update_frozen_req_file(REQ_FILE_PATH, all_packages=True)

        assert errors == []
        written_content = mock_write_file.call_args[0][1]
        assert PIP_FREEZE_COMMENT in written_content
        assert REQ_FILE_PACKAGES[2] in written_content

    def test_all_packages_true_pip_comment_is_kept(self, mock_frozen_path_valid, mock_read_file, mock_write_file):
        lines = [
            REQ_FILE_PACKAGES[0],
            PIP_FREEZE_COMMENT,
            REQ_FILE_PACKAGES[2],
        ]

        # noinspection PyUnusedLocal
        def _side_effect(exit_code, cmd, extra_args, lines_output):
            lines_output.extend(lines)

        with patch('aedev.project_manager.utils.sh_exit_if_exec_err', side_effect=_side_effect):
            errors = update_frozen_req_file(REQ_FILE_PATH, all_packages=True)

        assert errors == []
        written_content = mock_write_file.call_args[0][1]
        assert PIP_FREEZE_COMMENT in written_content

    def test_editable_install_project_dir_exists_version_substituted(
            self, mock_frozen_path_valid, mock_read_file, mock_write_file, mock_project_dev_vars):
        # noinspection PyUnusedLocal
        def _side_effect(exit_code, cmd, extra_args, lines_output):
            lines_output.extend([EDITABLE_LINE] + REQ_FILE_PACKAGES)

        with (patch("aedev.project_manager.utils.sh_exit_if_exec_err", side_effect=_side_effect),
              patch("aedev.project_manager.utils.os_path_isdir", return_value=True),
              patch("aedev.project_manager.utils.os_path_join", return_value=os.path.join("..", PRJ_NAME))):
            errors = update_frozen_req_file(REQ_FILE_PATH, all_packages=False)

        assert errors == []
        written_content = mock_write_file.call_args[0][1]
        expected_line = f"{PRJ_NAME}=={PRJ_VERSION}  # {EDITABLE_LINE}"
        assert expected_line in written_content
        assert EDITABLE_LINE not in written_content.replace(expected_line, "")

    def test_editable_install_project_dir_not_exists_line_unchanged(
            self, mock_frozen_path_valid, mock_read_file, mock_write_file):
        # noinspection PyUnusedLocal
        def _side_effect(exit_code, cmd, extra_args, lines_output):
            lines_output.extend([EDITABLE_LINE] + REQ_FILE_PACKAGES)

        with (patch("aedev.project_manager.utils.sh_exit_if_exec_err", side_effect=_side_effect),
              patch("aedev.project_manager.utils.os_path_isdir", return_value=False),
              patch("aedev.project_manager.utils.os_path_join", return_value=os.path.join("..", PRJ_NAME))):
            errors = update_frozen_req_file(REQ_FILE_PATH, all_packages=False)

        assert errors == []
        assert EDITABLE_LINE in mock_write_file.call_args[0][1]

    def test_first_line_refreshable_marker_is_stripped(self, mock_frozen_path_valid, mock_read_file, mock_write_file):
        refreshable_first_line = f"{REFRESHABLE_TEMPLATE_MARKER} do not edit manually"

        # noinspection PyUnusedLocal
        def _side_effect(exit_code, cmd, extra_args, lines_output):
            lines_output.extend([refreshable_first_line] + REQ_FILE_PACKAGES)

        with patch("aedev.project_manager.utils.sh_exit_if_exec_err", side_effect=_side_effect):
            errors = update_frozen_req_file(REQ_FILE_PATH, all_packages=False)

        assert errors == []
        written_content = mock_write_file.call_args[0][1]
        assert refreshable_first_line not in written_content
        assert REQ_FILE_PACKAGES[0] in written_content
        assert REQ_FILE_PACKAGES[1] in written_content
        assert REQ_FILE_PACKAGES[2] in written_content

    def test_first_line_without_refreshable_marker_kept(self, mock_frozen_path_valid, mock_read_file, mock_write_file):
        # noinspection PyUnusedLocal
        def _side_effect(exit_code, cmd, extra_args, lines_output):
            lines_output.extend(REQ_FILE_PACKAGES)

        with patch("aedev.project_manager.utils.sh_exit_if_exec_err", side_effect=_side_effect):
            errors = update_frozen_req_file(REQ_FILE_PATH, all_packages=False)

        assert errors == []
        written_content = mock_write_file.call_args[0][1]
        assert REQ_FILE_PACKAGES[0] in written_content
        assert REQ_FILE_PACKAGES[1] in written_content
        assert REQ_FILE_PACKAGES[2] in written_content

    def test_frozen_file_path_falsy_returns_empty_list_immediately(self, mock_frozen_path_none):
        with (patch("aedev.project_manager.utils.sh_exit_if_exec_err") as mock_exec,
              patch("aedev.project_manager.utils.write_file") as mock_write):
            errors = update_frozen_req_file(REQ_FILE_PATH)

        assert errors == []
        mock_exec.assert_not_called()
        mock_write.assert_not_called()
        mock_frozen_path_none.assert_called_once_with(REQ_FILE_PATH, strict=True)

    def test_no_errors_writes_file_and_returns_empty_list(
            self, mock_frozen_path_valid, mock_sh_exit_no_errors, mock_read_file, mock_write_file):
        errors = update_frozen_req_file(REQ_FILE_PATH)

        assert errors == []
        mock_write_file.assert_called_once_with(FROZEN_FILE_PATH, REQ_FILE_CONTENT)

    def test_stderr_errors_present_returns_error_list_without_writing_file(
            self, mock_frozen_path_valid, mock_sh_exit_with_stderr_errors, mock_write_file):
        with (patch("aedev.project_manager.utils.STDERR_END_MARKER", STDERR_END_MARKER),
              patch("aedev.project_manager.utils.STDERR_BEG_MARKER", STDERR_BEG_MARKER)):
            errors = update_frozen_req_file(REQ_FILE_PATH)

        assert errors == [TestUpdateFrozenReqFile.PIP_WARNING]
        mock_write_file.assert_not_called()

    def test_stderr_markers_present_no_error_messages_continues_normally(
            self, mock_frozen_path_valid, mock_sh_exit_with_stderr_no_error_messages, mock_read_file, mock_write_file):
        with (patch("aedev.project_manager.utils.STDERR_END_MARKER", STDERR_END_MARKER),
              patch("aedev.project_manager.utils.STDERR_BEG_MARKER", STDERR_BEG_MARKER)):
            errors = update_frozen_req_file(REQ_FILE_PATH)

        assert errors == []
        mock_write_file.assert_called_once()

    def test_stderr_no_markers_in_output_no_errors_returned(
            self, mock_frozen_path_valid, mock_sh_exit_no_errors, mock_read_file, mock_write_file):
        with patch("aedev.project_manager.utils.STDERR_END_MARKER", STDERR_END_MARKER):
            errors = update_frozen_req_file(REQ_FILE_PATH)

        assert errors == []

    def test_sh_exit_called_with_correct_arguments(
            self, mock_frozen_path_valid, mock_sh_exit_no_errors, mock_read_file, mock_write_file):
        update_frozen_req_file(REQ_FILE_PATH)

        mock_sh_exit_no_errors.assert_called_once()
        call_kwargs = mock_sh_exit_no_errors.call_args
        assert call_kwargs[0][0] == 73  # exit_code
        assert call_kwargs[0][1] == PIP_CMD  # cmd
        assert call_kwargs[1]["extra_args"] == ("freeze", "-r", REQ_FILE_PATH)
        assert isinstance(call_kwargs[1]["lines_output"], list)

    def test_write_file_called_w_frozen_path_and_content(self, mock_frozen_path_valid, mock_read_file, mock_write_file):
        # noinspection PyUnusedLocal
        def _side_effect(exit_code, cmd, extra_args, lines_output):
            lines_output.extend(REQ_FILE_PACKAGES)

        with patch("aedev.project_manager.utils.sh_exit_if_exec_err", side_effect=_side_effect):
            update_frozen_req_file(REQ_FILE_PATH, all_packages=False)

        mock_write_file.assert_called_once_with(FROZEN_FILE_PATH, REQ_FILE_CONTENT)


class TestOtherHelpers:
    @pytest.mark.parametrize('mock_pdv',
                             [{'project_type': ROOT_PRJ}, {'project_type': PARENT_PRJ}],
                             ids=['namespace-root', 'project-parent'], indirect=True)
    def test_children_desc_for_generic_children(self, mock_pdv, pdv_factory):
        desc = children_desc(mock_pdv, [pdv_factory({'project_type': MODULE_PRJ})])
        assert PORTION_NAME in desc
        assert ("portions" if mock_pdv['project_type'] == ROOT_PRJ else "children") in desc

    def test_children_desc_for_projects_parent(self, pdv_factory):
        desc = children_desc(pdv_factory({'project_type': ROOT_PRJ}), [pdv_factory({'project_type': MODULE_PRJ})])
        assert PORTION_NAME in desc
        assert "portions" in desc

    def test_children_project_names(self, pdv_factory):
        root_pdv = pdv_factory({'project_type': ROOT_PRJ})
        child_name = f"{root_pdv['namespace_name']}_{PORTION_NAME}"
        assert children_project_names(root_pdv,
                                      [child_name],
                                      OrderedDict({child_name: pdv_factory({'project_type': MODULE_PRJ})}))

    def test_expected_args(self):
        spe = {'arg_names': (('varA_arg1', 'varA_arg2'), ('varB_arg1', 'varB_arg2', 'varB_arg3'))}
        assert expected_args(spe) == "varA_arg1 varA_arg2 -or- varB_arg1 varB_arg2 varB_arg3"

        spe = {'arg_names': (('a', 'b'), ('c', ), ('d', ))}
        assert expected_args(spe) == "a b -or- c -or- d"

        spe = {'arg_names': (('a', 'b'), ('c', ), ('d', )), 'flags': {'FLAG': False}}
        assert expected_args(spe).startswith("a b -or- c -or- d")
        assert "FLAG=False" in expected_args(spe)

        spe = {'flags': {'FLAG': False}}
        assert "FLAG=False" in expected_args(spe)

    def test_get_app_option(self, mock_pdv):
        assert get_app_option(mock_pdv, "option_name") is None

    def test_get_branch(self, cons_app, mocked_app_options, module_repo_path):
        branch = "tst_branch_name"
        mocked_app_options['branch'] = branch
        pdv = pdv_with_email(project_path=os_path_dirname(module_repo_path))

        assert get_branch(pdv) == branch

        mocked_app_options['branch'] = ""
        with patch('aedev.project_manager.utils.git_current_branch', return_value=branch):
            assert get_branch(pdv) == branch

    def test_get_host_class_name_invalid_host_name(self):
        assert get_host_class_name("not.existing.host.class-name ") == ""
        assert get_host_class_name(" invalid or not existing host class name ") == ""

    def test_get_host_config_val(self, mock_pdv):
        assert get_host_config_val(mock_pdv, "option_name", host_domain="host.domain", host_user="host_usr") is None

    @pytest.mark.parametrize('mock_pdv',
                             [{'project_type': ROOT_PRJ}, {'project_type': MODULE_PRJ}],
                             ids=['namespace-root', 'module'], indirect=True)
    def test_get_host_domain(self, mock_pdv):
        assert get_host_domain(mock_pdv) == ""
        assert get_host_domain(mock_pdv, var_prefix="xxx") == ""

    def test_get_host_group(self, mock_pdv):
        assert get_host_group(mock_pdv, "host.domain") == ""

    def test_get_host_user_name(self, cons_app, mocked_app_options, module_repo_path, monkeypatch):
        # monkeypatch.delenv('PDV_AUTHOR', raising=False)
        # monkeypatch.delenv('AE_OPTIONS_REPO_USER', raising=False)
        # monkeypatch.delenv('AE_OPTIONS_REPO_USER_AT_GITLAB_COM', raising=False)
        project_path = module_repo_path
        parent_path = os_path_dirname(project_path)
        tst_domain = 'tst_do.main.com'
        t_domain2 = 'test.domain2.tst'

        with in_wd(project_path):   # prevent reading from .env in project_manager root or src parent
            usr_nam = tst_ns_name + PDV_REPO_GROUP_SUFFIX   # default user name for namespace module / module_repo_path

            assert get_host_user_name(pdv_with_email(project_path=project_path), "NotGitLabToIgnoreLocEnvs") == usr_nam

            # tests ordered by priority; first test with the lowest priority: get .env variable w/o domain in parent dir

            usr_nam = "usr_nam_via_group_name_command_line_option"
            mocked_app_options['repo_group'] = usr_nam

            assert get_host_user_name(pdv_with_email(project_path=project_path), "") == usr_nam

            var_nam = f"{ENV_VAR_NAME_PREFIX}repo_user"
            usr_nam = 'usr_nam_via_PDV_var_in_parent_.env'
            write_file(os_path_join(parent_path, ".env"), f"\n{var_nam}={usr_nam}\n", extra_mode='a')

            assert get_host_user_name(pdv_with_email(project_path=project_path), "") == usr_nam
            assert get_host_user_name(pdv_with_email(project_path=project_path), tst_domain) == usr_nam

            var_nam = f"{ENV_VAR_NAME_PREFIX}repo_user"
            usr_nam = 'usr_nam_via_PDV_var_in_.env'
            write_file(os_path_join(project_path, ".env"), f"\n{var_nam}={usr_nam}\n", extra_mode='a')

            assert get_host_user_name(pdv_with_email(project_path=project_path), tst_domain) == usr_nam
            assert get_host_user_name(pdv_with_email(project_path=project_path), "") == usr_nam

            var_nam = f"{ENV_VAR_NAME_PREFIX}repo_user"
            usr_nam = 'usr_nam_via_PDV_var_in_os.environ'
            monkeypatch.setenv(var_nam, usr_nam)

            assert get_host_user_name(pdv_with_email(project_path=project_path), "") == usr_nam
            assert get_host_user_name(pdv_with_email(project_path=project_path), t_domain2) == usr_nam

            var_nam = "AE_OPTIONS_REPO_USER"
            usr_nam = 'usr_nam_via_parent_.env_and_without_domain'
            write_file(os_path_join(parent_path, ".env"), f"\n{var_nam}={usr_nam}\n", extra_mode='a')

            assert get_host_user_name(pdv_with_email(project_path=project_path), "") == usr_nam

            var_nam = f"AE_OPTIONS_REPO_USER_AT_{norm_name(tst_domain).upper()}"
            usr_nam = 'usr_nam_via_parent_.env_and_with_domain'
            write_file(os_path_join(parent_path, ".env"), f"\n{var_nam}={usr_nam}\n", extra_mode='a')

            assert get_host_user_name(pdv_with_email(project_path=project_path), tst_domain) == usr_nam

            var_nam = "AE_OPTIONS_REPO_USER"
            usr_nam = 'usr_nam_via_.env_and_without_domain'
            write_file(os_path_join(project_path, ".env"), f"\n{var_nam}={usr_nam}\n", extra_mode='a')

            assert get_host_user_name(pdv_with_email(project_path=project_path), "") == usr_nam

            var_nam = f"AE_OPTIONS_REPO_USER_AT_{norm_name(tst_domain).upper()}"
            usr_nam = 'usr_nam_via_.env_and_with_domain'
            write_file(os_path_join(parent_path, ".env"), f"\n{var_nam}={usr_nam}\n", extra_mode='a')

            assert get_host_user_name(pdv_with_email(project_path=project_path), tst_domain) == usr_nam

            var_nam = "AE_OPTIONS_REPO_USER"
            usr_nam = 'usr_nam_via_environ_and_without_domain'
            monkeypatch.setenv(var_nam, usr_nam)

            assert get_host_user_name(pdv_with_email(project_path=project_path), "") == usr_nam

            var_nam = f"AE_OPTIONS_REPO_USER_AT_{norm_name(tst_domain).upper()}"
            usr_nam = 'usr_nam_via_environ_and_with_domain'
            monkeypatch.setenv(var_nam, usr_nam)

            assert get_host_user_name(pdv_with_email(project_path=project_path), tst_domain) == usr_nam

            var_nam = f"AE_OPTIONS_REPO_USER_AT_{norm_name(t_domain2).upper()}"
            usr_nam = 'usr_nam_via_.env_and_with_domain_set_via_command_line_option'
            mocked_app_options['repo_domain'] = t_domain2
            write_file(os_path_join(parent_path, ".env"), f"\n{var_nam}={usr_nam}\n", extra_mode='a')

            assert get_host_user_name(pdv_with_email(project_path=project_path), "") == usr_nam
            assert get_host_user_name(pdv_with_email(project_path=project_path), t_domain2) == usr_nam

            usr_nam = "usr_nam_via_command_line_option"
            mocked_app_options['repo_user'] = usr_nam

            assert get_host_user_name(pdv_with_email(project_path=project_path), tst_domain) == usr_nam

    def test_get_host_user_token(self, cons_app, empty_repo_path, mocked_app_options, monkeypatch):
        # these tests would fail ONLY if run via "pjm check" because the tokens get loaded from .env by pjm
        for env_var in os.environ:
            if "REPO_TOKEN" in env_var.upper():  # AE_OPTIONS... or PDV_repo_token
                print(f"   ## temp. unload of variable {env_var} for unit test")
                monkeypatch.delenv(env_var)

        parent_path = os_path_dirname(empty_repo_path)
        tst_domain = 't.s.t_do.main.com'
        t_domain2 = 't.s.t.domain2.t.st'
        user_name = 'TstUserName'

        with in_wd(empty_repo_path):  # prevent reading from .env in pdv_with_email([project_path="."]) instantiation
            usr_tok = ""  # user token default is an empty string

            assert get_host_user_token(pdv_with_email(), "NotGitLabToIgnoreLocEnvs") == usr_tok

            # tests ordered by priority; first test with the lowest priority: get .env variable w/o domain in parent dir

            var_nam = f"{ENV_VAR_NAME_PREFIX}repo_token"
            usr_tok = 'usr_tok_via_PDV_var_in_parent_.env'
            write_file(os_path_join(parent_path, ".env"), f"\n{var_nam}={usr_tok}\n", extra_mode='a')

            assert get_host_user_token(pdv_with_email(), "") == usr_tok
            assert get_host_user_token(pdv_with_email(), tst_domain) == usr_tok

            var_nam = f"{ENV_VAR_NAME_PREFIX}repo_token"
            usr_tok = 'usr_tok_via_PDV_var_in_.env'
            write_file(".env", f"\n{var_nam}={usr_tok}\n", extra_mode='a')

            assert get_host_user_token(pdv_with_email(), tst_domain) == usr_tok
            assert get_host_user_token(pdv_with_email(), "") == usr_tok

            var_nam = f"{ENV_VAR_NAME_PREFIX}repo_token"
            usr_tok = 'usr_tok_via_PDV_var_in_os.environ'
            monkeypatch.setenv(var_nam, usr_tok)

            assert get_host_user_token(pdv_with_email(), "") == usr_tok
            assert get_host_user_token(pdv_with_email(), t_domain2) == usr_tok

            var_nam = "AE_OPTIONS_REPO_TOKEN"
            usr_tok = 'usr_tok_via_parent_.env_and_without_domain'
            write_file(os_path_join(parent_path, ".env"), f"\n{var_nam}={usr_tok}\n", extra_mode='a')

            assert get_host_user_token(pdv_with_email(), "") == usr_tok

            var_nam = f"AE_OPTIONS_REPO_TOKEN_AT_{norm_name(tst_domain).upper()}"
            usr_tok = 'usr_tok_via_parent_.env_and_with_domain'
            write_file(os_path_join(parent_path, ".env"), f"\n{var_nam}={usr_tok}\n", extra_mode='a')

            assert get_host_user_token(pdv_with_email(), tst_domain) == usr_tok

            var_nam = f"AE_OPTIONS_REPO_TOKEN_AT_{norm_name(tst_domain).upper()}_{user_name.upper()}"
            usr_tok = 'usr_tok_via_parent_.env_and_with_domain_and_user'
            write_file(os_path_join(parent_path, ".env"), f"\n{var_nam}={usr_tok}\n", extra_mode='a')

            assert get_host_user_token(pdv_with_email(), tst_domain, host_user=user_name) == usr_tok

            var_nam = "AE_OPTIONS_REPO_TOKEN"
            usr_tok = 'usr_tok_via_.env_and_without_domain'
            write_file(".env", f"\n{var_nam}={usr_tok}\n", extra_mode='a')

            assert get_host_user_token(pdv_with_email(), "") == usr_tok

            var_nam = f"AE_OPTIONS_REPO_TOKEN_AT_{norm_name(tst_domain).upper()}"
            usr_tok = 'usr_tok_via_.env_and_with_domain'
            write_file(os_path_join(parent_path, ".env"), f"\n{var_nam}={usr_tok}\n", extra_mode='a')

            assert get_host_user_token(pdv_with_email(), tst_domain) == usr_tok

            var_nam = f"AE_OPTIONS_REPO_TOKEN_AT_{norm_name(tst_domain).upper()}_{user_name.upper()}"
            usr_tok = 'usr_tok_via_.env_and_with_domain_and_user'
            write_file(os_path_join(parent_path, ".env"), f"\n{var_nam}={usr_tok}\n", extra_mode='a')

            assert get_host_user_token(pdv_with_email(), tst_domain, host_user=user_name) == usr_tok

            var_nam = "AE_OPTIONS_REPO_TOKEN"
            usr_tok = 'usr_tok_via_environ_and_without_domain'
            monkeypatch.setenv(var_nam, usr_tok)

            assert get_host_user_token(pdv_with_email(), "") == usr_tok

            var_nam = f"AE_OPTIONS_REPO_TOKEN_AT_{norm_name(tst_domain).upper()}"
            usr_tok = 'usr_tok_via_environ_and_with_domain'
            monkeypatch.setenv(var_nam, usr_tok)

            assert get_host_user_token(pdv_with_email(), tst_domain) == usr_tok

            var_nam = f"AE_OPTIONS_REPO_TOKEN_AT_{norm_name(tst_domain).upper()}_{user_name.upper()}"
            usr_tok = 'usr_tok_via_environ_and_with_domain_and_user'
            monkeypatch.setenv(var_nam, usr_tok)

            assert get_host_user_token(pdv_with_email(), tst_domain, host_user=user_name) == usr_tok

            var_nam = f"AE_OPTIONS_REPO_TOKEN_AT_{norm_name(t_domain2).upper()}"
            usr_tok = 'usr_tok_via_.env_and_with_domain_set_via_command_line_option'
            mocked_app_options['repo_domain'] = t_domain2
            write_file(os_path_join(parent_path, ".env"), f"\n{var_nam}={usr_tok}\n", extra_mode='a')

            assert get_host_user_token(pdv_with_email(), "") == usr_tok
            assert get_host_user_token(pdv_with_email(), t_domain2) == usr_tok

            var_nam = f"AE_OPTIONS_REPO_TOKEN_AT_{norm_name(t_domain2).upper()}_{user_name.upper()}"
            usr_tok = 'usr_tok_via_.env_and_with_domain_set_via_command_line_option_and_with_user'
            mocked_app_options['repo_domain'] = t_domain2
            write_file(os_path_join(parent_path, ".env"), f"\n{var_nam}={usr_tok}\n", extra_mode='a')

            assert get_host_user_token(pdv_with_email(), "", host_user=user_name) == usr_tok
            assert get_host_user_token(pdv_with_email(), t_domain2, host_user=user_name) == usr_tok

            usr_tok = "usr_tok_via_command_line_option"
            mocked_app_options['repo_token'] = usr_tok

            assert get_host_user_token(pdv_with_email(), tst_domain) == usr_tok

        token = "t_s_t__usr_token"
        pdv = pdv_with_email(project_path=empty_repo_path)

        mocked_app_options['repo_token'] = token
        assert get_host_user_token(pdv, "") == token
        assert get_host_user_token(pdv, "", host_user="not_configured_user_name") == token

        with patch('aedev.project_manager.utils.get_host_group', return_value=token):
            assert get_host_user_token(pdv, "domain.xxx") == token
            assert get_host_user_token(pdv, "not_configured_domain", host_user="not_configured_user_name") == token

    def test_get_mirror_urls(self, monkeypatch):
        pdv = pdv_with_email()
        monkeypatch.delenv('PJM_MIRROR_REMOTE_EXPRESSIONS', raising=False)

        assert get_mirror_urls(pdv) == []

        monkeypatch.setenv('PJM_MIRROR_REMOTE_EXPRESSIONS', "")

        assert get_mirror_urls(pdv) == []

        monkeypatch.setenv('PJM_MIRROR_REMOTE_EXPRESSIONS', "[project_version, ]")

        assert get_mirror_urls(pdv) == [pdv['project_version']]

        monkeypatch.setenv('PJM_MIRROR_REMOTE_EXPRESSIONS', "[project_name, 'url']")

        assert get_mirror_urls(pdv) == [pdv['project_name'], 'url']

        monkeypatch.setenv('PJM_MIRROR_REMOTE_EXPRESSIONS', "('tst_url' if project_version else '', False or '')")

        assert get_mirror_urls(pdv) == ['tst_url']

    def test_git_init_add(self, mock_pdv):
        with (patch('aedev.project_manager.utils.git_init_if_needed', return_value=False) as ini,
              patch('aedev.project_manager.utils.git_add') as add):
            git_init_add(mock_pdv)
            ini.call_args.assert_called_with(project_path=PRJ_ROOT_PATH)
            add.call_args.assert_called_with([PRJ_ROOT_PATH])

    def test_git_push_url(self, mock_pdv):
        assert git_push_url(mock_pdv)

    def test_guess_next_action_on_local_machine_only(self, empty_repo_path):
        git_checkout(empty_repo_path, "--detach")

        ret = guess_next_action(pdv_with_email(project_path=empty_repo_path))

        assert ret.startswith("¡detached HEAD")

        git_checkout(empty_repo_path, DEF_MAIN_BRANCH)

        ret = guess_next_action(pdv_with_email(project_path=empty_repo_path))

        assert ret.startswith("¡empty or invalid project version")

        ensure_tst_ns_portion_version_file(empty_repo_path)

        ret = guess_next_action(pdv_with_email(project_path=empty_repo_path))

        assert ret.startswith(uncommitted_guess_prefix)

        new_branch = 'new_feature_branch_name_testing_guest_next_action' + now_str(sep="_")
        git_checkout(empty_repo_path, new_branch=new_branch)

        ret = guess_next_action(pdv_with_email(project_path=empty_repo_path))

        assert ret.startswith(f"¡unstaged files found")

        git_add(empty_repo_path)

        ret = guess_next_action(pdv_with_email(project_path=empty_repo_path))

        assert ret == 'prepare_commit'

        write_file(os_path_join(empty_repo_path, COMMIT_MSG_FILE_NAME), "msg-title without project_version placeholder")

        ret = guess_next_action(pdv_with_email(project_path=empty_repo_path))

        assert ret == 'prepare_commit'

        write_file(os_path_join(empty_repo_path, COMMIT_MSG_FILE_NAME), "msg-title V {project_version}")

        ret = guess_next_action(pdv_with_email(project_path=empty_repo_path))

        assert ret == 'commit_project'

        git_commit(empty_repo_path, tst_pkg_version)
        git_checkout(empty_repo_path, DEF_MAIN_BRANCH)
        ensure_tst_ns_portion_version_file(empty_repo_path)
        git_add(empty_repo_path)
        git_commit(empty_repo_path, tst_pkg_version)

        ret = guess_next_action(pdv_with_email(project_path=empty_repo_path))

        assert ret == 'renew_project'

        # NOT TESTABLE because ret.startswith("¡detached HEAD") if .git gets renamed
        # os.rename(os_path_join(empty_repo_path, ".git"), os_path_join(empty_repo_path, '_renamed_git_folder'))
        #
        # ret = guess_next_action(pdv_with_email(project_path=empty_repo_path))
        #
        # assert ret.startswith("¡no git workflow initiated")
        # assert "start a new project" in ret
        #
        # os.rename(os_path_join(empty_repo_path, '_renamed_git_folder'), os_path_join(empty_repo_path, ".git"))

        git_checkout(empty_repo_path, new_branch)

        ret = guess_next_action(pdv_with_email(project_path=empty_repo_path))

        assert ret == 'push_project'

    def test_guess_next_action_fix_empty_on_local_machine_only(self, empty_repo_path):
        assert guess_next_action(pdv_with_email(project_path=empty_repo_path)).startswith("¡")

        ensure_tst_ns_portion_version_file(empty_repo_path)
        git_checkout(empty_repo_path, new_branch='new_feature_branch_name_testing_guest_next_action' + now_str(sep="_"))
        write_file(os_path_join(empty_repo_path, COMMIT_MSG_FILE_NAME), "msg-title V {project_version}")
        git_add(empty_repo_path)

        assert guess_next_action(pdv_with_email(project_path=empty_repo_path)) == 'commit_project'

    def test_ppp(self):
        assert ppp("") == ""

    def test_project_topics(self, empty_repo_path):
        pdv = pdv_with_email(project_path=empty_repo_path)
        assert isinstance(project_topics(pdv), list)
        assert project_topics(pdv)

        pdv.pdv_val('setup_kwargs')['classifiers'] = []
        assert project_topics(pdv) == []

    def test_update_frozen_req_file(self):
        assert not update_frozen_req_file("")

    def test_refresh_pdv(self, mock_pdv):
        refresh_pdv(mock_pdv)
        assert mock_pdv['project_path'] == PRJ_ROOT_PATH

    def test_update_frozen_req_files_frozen_dev_req(self, empty_repo_path, recwarn):
        pdv = ProjectDevVars(project_path=empty_repo_path)

        assert not update_frozen_req_files(pdv)
        assert not pdv['dev_requires']

        pgk_names = ["package_name1", "package_name2"]
        write_file(os_path_join(empty_repo_path, pdv['REQ_DEV_FILE_NAME']), "\n".join(pgk_names))

        assert not update_frozen_req_files(pdv)
        assert pdv['dev_requires']

        assert len(recwarn) == 2
        assert "value of 'var_name='dev_requires'' is not of type str" in recwarn[0].message.args[0]
        assert "value of 'var_name='dev_requires'' is not of type str" in recwarn[1].message.args[0]

    def test_update_frozen_req_files_frozen_docs_req(self, empty_repo_path):
        pdv = pdv_with_email(project_path=empty_repo_path)
        pgk_names = ["package_name1", "package_name2"]
        req_file_name = os_path_join(empty_repo_path, os_path_join(pdv['DOCS_FOLDER'], pdv['REQ_FILE_NAME']))
        assert not os_path_isfile(frozen_req_file_path(req_file_name))
        assert not update_frozen_req_files(pdv)

        write_file(req_file_name, "\n".join(pgk_names), make_dirs=True)
        write_file(frozen_req_file_path(req_file_name), "\n".join(pgk_names))

        assert not update_frozen_req_files(pdv)

    def test_write_commit_message_without_frozen_req_files(self, module_repo_path):
        pdv = pdv_with_email(project_path=module_repo_path)
        pkg_ver = "2.4.6 or a {project_version} placeholder"

        assert not os_path_isfile(os_path_join(module_repo_path, pdv['COMMIT_MSG_FILE_NAME']))

        write_commit_message(pdv, pkg_version=pkg_ver)

        assert os_path_isfile(os_path_join(module_repo_path, pdv['COMMIT_MSG_FILE_NAME']))

        content = read_file(os_path_join(module_repo_path, pdv['COMMIT_MSG_FILE_NAME']))
        assert pkg_ver in content
        assert git_current_branch(module_repo_path).replace("_", " ") in content
