""" utils module tests. """
import os

from unittest.mock import patch

from ae.base import in_wd, norm_name, now_str, os_path_dirname, os_path_join, write_file

from aedev.base import COMMIT_MSG_FILE_NAME, DEF_MAIN_BRANCH
from aedev.commands import git_add, git_checkout, git_commit
from aedev.project_vars import ENV_VAR_NAME_PREFIX, PDV_REPO_GROUP_SUFFIX, ProjectDevVars

from constants_and_fixtures import (
    empty_repo_path, ensure_tst_ns_portion_version_file, mocked_app_options, module_repo_path,
    tst_ns_name, tst_pkg_version, uncommitted_guess_prefix)

from aedev.project_manager.utils import (
    expected_args, get_branch, get_host_user_name, get_host_user_token, get_mirror_urls, guess_next_action)


class TestHelpers:
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

    def test_get_branch(self, cons_app, mocked_app_options, module_repo_path):
        branch = "tst_branch_name"
        mocked_app_options['branch'] = branch
        pdv = ProjectDevVars(project_path=os_path_dirname(module_repo_path))

        assert get_branch(pdv) == branch

        mocked_app_options['branch'] = ""
        with patch('aedev.project_manager.utils.git_current_branch', return_value=branch):
            assert get_branch(pdv) == branch

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

            assert get_host_user_name(ProjectDevVars(project_path=project_path), "NotGitLabToIgnoreLocEnvs") == usr_nam

            # tests ordered by priority; first test with the lowest priority: get .env variable w/o domain in parent dir

            usr_nam = "usr_nam_via_group_name_command_line_option"
            mocked_app_options['repo_group'] = usr_nam

            assert get_host_user_name(ProjectDevVars(project_path=project_path), "") == usr_nam

            var_nam = f"{ENV_VAR_NAME_PREFIX}repo_user"
            usr_nam = 'usr_nam_via_PDV_var_in_parent_.env'
            write_file(os_path_join(parent_path, ".env"), f"\n{var_nam}={usr_nam}\n", extra_mode='a')

            assert get_host_user_name(ProjectDevVars(project_path=project_path), "") == usr_nam
            assert get_host_user_name(ProjectDevVars(project_path=project_path), tst_domain) == usr_nam

            var_nam = f"{ENV_VAR_NAME_PREFIX}repo_user"
            usr_nam = 'usr_nam_via_PDV_var_in_.env'
            write_file(os_path_join(project_path, ".env"), f"\n{var_nam}={usr_nam}\n", extra_mode='a')

            assert get_host_user_name(ProjectDevVars(project_path=project_path), tst_domain) == usr_nam
            assert get_host_user_name(ProjectDevVars(project_path=project_path), "") == usr_nam

            var_nam = f"{ENV_VAR_NAME_PREFIX}repo_user"
            usr_nam = 'usr_nam_via_PDV_var_in_os.environ'
            monkeypatch.setenv(var_nam, usr_nam)

            assert get_host_user_name(ProjectDevVars(project_path=project_path), "") == usr_nam
            assert get_host_user_name(ProjectDevVars(project_path=project_path), t_domain2) == usr_nam

            var_nam = "AE_OPTIONS_REPO_USER"
            usr_nam = 'usr_nam_via_parent_.env_and_without_domain'
            write_file(os_path_join(parent_path, ".env"), f"\n{var_nam}={usr_nam}\n", extra_mode='a')

            assert get_host_user_name(ProjectDevVars(project_path=project_path), "") == usr_nam

            var_nam = f"AE_OPTIONS_REPO_USER_AT_{norm_name(tst_domain).upper()}"
            usr_nam = 'usr_nam_via_parent_.env_and_with_domain'
            write_file(os_path_join(parent_path, ".env"), f"\n{var_nam}={usr_nam}\n", extra_mode='a')

            assert get_host_user_name(ProjectDevVars(project_path=project_path), tst_domain) == usr_nam

            var_nam = "AE_OPTIONS_REPO_USER"
            usr_nam = 'usr_nam_via_.env_and_without_domain'
            write_file(os_path_join(project_path, ".env"), f"\n{var_nam}={usr_nam}\n", extra_mode='a')

            assert get_host_user_name(ProjectDevVars(project_path=project_path), "") == usr_nam

            var_nam = f"AE_OPTIONS_REPO_USER_AT_{norm_name(tst_domain).upper()}"
            usr_nam = 'usr_nam_via_.env_and_with_domain'
            write_file(os_path_join(parent_path, ".env"), f"\n{var_nam}={usr_nam}\n", extra_mode='a')

            assert get_host_user_name(ProjectDevVars(project_path=project_path), tst_domain) == usr_nam

            var_nam = "AE_OPTIONS_REPO_USER"
            usr_nam = 'usr_nam_via_environ_and_without_domain'
            monkeypatch.setenv(var_nam, usr_nam)

            assert get_host_user_name(ProjectDevVars(project_path=project_path), "") == usr_nam

            var_nam = f"AE_OPTIONS_REPO_USER_AT_{norm_name(tst_domain).upper()}"
            usr_nam = 'usr_nam_via_environ_and_with_domain'
            monkeypatch.setenv(var_nam, usr_nam)

            assert get_host_user_name(ProjectDevVars(project_path=project_path), tst_domain) == usr_nam

            var_nam = f"AE_OPTIONS_REPO_USER_AT_{norm_name(t_domain2).upper()}"
            usr_nam = 'usr_nam_via_.env_and_with_domain_set_via_command_line_option'
            mocked_app_options['repo_domain'] = t_domain2
            write_file(os_path_join(parent_path, ".env"), f"\n{var_nam}={usr_nam}\n", extra_mode='a')

            assert get_host_user_name(ProjectDevVars(project_path=project_path), "") == usr_nam
            assert get_host_user_name(ProjectDevVars(project_path=project_path), t_domain2) == usr_nam

            usr_nam = "usr_nam_via_command_line_option"
            mocked_app_options['repo_user'] = usr_nam

            assert get_host_user_name(ProjectDevVars(project_path=project_path), tst_domain) == usr_nam

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

        with in_wd(empty_repo_path):  # prevent reading from .env in ProjectDevVars([project_path="."]) instantiation
            usr_tok = ""  # user token default is an empty string

            assert get_host_user_token(ProjectDevVars(), "NotGitLabToIgnoreLocEnvs") == usr_tok

            # tests ordered by priority; first test with the lowest priority: get .env variable w/o domain in parent dir

            var_nam = f"{ENV_VAR_NAME_PREFIX}repo_token"
            usr_tok = 'usr_tok_via_PDV_var_in_parent_.env'
            write_file(os_path_join(parent_path, ".env"), f"\n{var_nam}={usr_tok}\n", extra_mode='a')

            assert get_host_user_token(ProjectDevVars(), "") == usr_tok
            assert get_host_user_token(ProjectDevVars(), tst_domain) == usr_tok

            var_nam = f"{ENV_VAR_NAME_PREFIX}repo_token"
            usr_tok = 'usr_tok_via_PDV_var_in_.env'
            write_file(".env", f"\n{var_nam}={usr_tok}\n", extra_mode='a')

            assert get_host_user_token(ProjectDevVars(), tst_domain) == usr_tok
            assert get_host_user_token(ProjectDevVars(), "") == usr_tok

            var_nam = f"{ENV_VAR_NAME_PREFIX}repo_token"
            usr_tok = 'usr_tok_via_PDV_var_in_os.environ'
            monkeypatch.setenv(var_nam, usr_tok)

            assert get_host_user_token(ProjectDevVars(), "") == usr_tok
            assert get_host_user_token(ProjectDevVars(), t_domain2) == usr_tok

            var_nam = "AE_OPTIONS_REPO_TOKEN"
            usr_tok = 'usr_tok_via_parent_.env_and_without_domain'
            write_file(os_path_join(parent_path, ".env"), f"\n{var_nam}={usr_tok}\n", extra_mode='a')

            assert get_host_user_token(ProjectDevVars(), "") == usr_tok

            var_nam = f"AE_OPTIONS_REPO_TOKEN_AT_{norm_name(tst_domain).upper()}"
            usr_tok = 'usr_tok_via_parent_.env_and_with_domain'
            write_file(os_path_join(parent_path, ".env"), f"\n{var_nam}={usr_tok}\n", extra_mode='a')

            assert get_host_user_token(ProjectDevVars(), tst_domain) == usr_tok

            var_nam = f"AE_OPTIONS_REPO_TOKEN_AT_{norm_name(tst_domain).upper()}_{user_name.upper()}"
            usr_tok = 'usr_tok_via_parent_.env_and_with_domain_and_user'
            write_file(os_path_join(parent_path, ".env"), f"\n{var_nam}={usr_tok}\n", extra_mode='a')

            assert get_host_user_token(ProjectDevVars(), tst_domain, host_user=user_name) == usr_tok

            var_nam = "AE_OPTIONS_REPO_TOKEN"
            usr_tok = 'usr_tok_via_.env_and_without_domain'
            write_file(".env", f"\n{var_nam}={usr_tok}\n", extra_mode='a')

            assert get_host_user_token(ProjectDevVars(), "") == usr_tok

            var_nam = f"AE_OPTIONS_REPO_TOKEN_AT_{norm_name(tst_domain).upper()}"
            usr_tok = 'usr_tok_via_.env_and_with_domain'
            write_file(os_path_join(parent_path, ".env"), f"\n{var_nam}={usr_tok}\n", extra_mode='a')

            assert get_host_user_token(ProjectDevVars(), tst_domain) == usr_tok

            var_nam = f"AE_OPTIONS_REPO_TOKEN_AT_{norm_name(tst_domain).upper()}_{user_name.upper()}"
            usr_tok = 'usr_tok_via_.env_and_with_domain_and_user'
            write_file(os_path_join(parent_path, ".env"), f"\n{var_nam}={usr_tok}\n", extra_mode='a')

            assert get_host_user_token(ProjectDevVars(), tst_domain, host_user=user_name) == usr_tok

            var_nam = "AE_OPTIONS_REPO_TOKEN"
            usr_tok = 'usr_tok_via_environ_and_without_domain'
            monkeypatch.setenv(var_nam, usr_tok)

            assert get_host_user_token(ProjectDevVars(), "") == usr_tok

            var_nam = f"AE_OPTIONS_REPO_TOKEN_AT_{norm_name(tst_domain).upper()}"
            usr_tok = 'usr_tok_via_environ_and_with_domain'
            monkeypatch.setenv(var_nam, usr_tok)

            assert get_host_user_token(ProjectDevVars(), tst_domain) == usr_tok

            var_nam = f"AE_OPTIONS_REPO_TOKEN_AT_{norm_name(tst_domain).upper()}_{user_name.upper()}"
            usr_tok = 'usr_tok_via_environ_and_with_domain_and_user'
            monkeypatch.setenv(var_nam, usr_tok)

            assert get_host_user_token(ProjectDevVars(), tst_domain, host_user=user_name) == usr_tok

            var_nam = f"AE_OPTIONS_REPO_TOKEN_AT_{norm_name(t_domain2).upper()}"
            usr_tok = 'usr_tok_via_.env_and_with_domain_set_via_command_line_option'
            mocked_app_options['repo_domain'] = t_domain2
            write_file(os_path_join(parent_path, ".env"), f"\n{var_nam}={usr_tok}\n", extra_mode='a')

            assert get_host_user_token(ProjectDevVars(), "") == usr_tok
            assert get_host_user_token(ProjectDevVars(), t_domain2) == usr_tok

            var_nam = f"AE_OPTIONS_REPO_TOKEN_AT_{norm_name(t_domain2).upper()}_{user_name.upper()}"
            usr_tok = 'usr_tok_via_.env_and_with_domain_set_via_command_line_option_and_with_user'
            mocked_app_options['repo_domain'] = t_domain2
            write_file(os_path_join(parent_path, ".env"), f"\n{var_nam}={usr_tok}\n", extra_mode='a')

            assert get_host_user_token(ProjectDevVars(), "", host_user=user_name) == usr_tok
            assert get_host_user_token(ProjectDevVars(), t_domain2, host_user=user_name) == usr_tok

            usr_tok = "usr_tok_via_command_line_option"
            mocked_app_options['repo_token'] = usr_tok

            assert get_host_user_token(ProjectDevVars(), tst_domain) == usr_tok

        token = "t_s_t__usr_token"
        pdv = ProjectDevVars(project_path=empty_repo_path)

        mocked_app_options['repo_token'] = token
        assert get_host_user_token(pdv, "") == token
        assert get_host_user_token(pdv, "", host_user="not_configured_user_name") == token

        with patch('aedev.project_manager.utils.get_host_group', return_value=token):
            assert get_host_user_token(pdv, "domain.xxx") == token
            assert get_host_user_token(pdv, "not_configured_domain", host_user="not_configured_user_name") == token

    def test_get_mirror_urls(self, monkeypatch):
        pdv = ProjectDevVars()
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

    def test_guess_next_action_on_local_machine_only(self, empty_repo_path):
        git_checkout(empty_repo_path, "--detach")

        ret = guess_next_action(ProjectDevVars(project_path=empty_repo_path))

        assert ret.startswith("¡detached HEAD")

        git_checkout(empty_repo_path, DEF_MAIN_BRANCH)

        ret = guess_next_action(ProjectDevVars(project_path=empty_repo_path))

        assert ret.startswith("¡empty or invalid project version")

        ensure_tst_ns_portion_version_file(empty_repo_path)

        ret = guess_next_action(ProjectDevVars(project_path=empty_repo_path))

        assert ret.startswith(uncommitted_guess_prefix)

        new_branch = 'new_feature_branch_name_testing_guest_next_action' + now_str(sep="_")
        git_checkout(empty_repo_path, new_branch=new_branch)

        ret = guess_next_action(ProjectDevVars(project_path=empty_repo_path))

        assert ret.startswith(f"¡unstaged files found")

        git_add(empty_repo_path)

        ret = guess_next_action(ProjectDevVars(project_path=empty_repo_path))

        assert ret == 'prepare_commit'

        write_file(os_path_join(empty_repo_path, COMMIT_MSG_FILE_NAME), "msg-title without project_version placeholder")

        ret = guess_next_action(ProjectDevVars(project_path=empty_repo_path))

        assert ret == 'prepare_commit'

        write_file(os_path_join(empty_repo_path, COMMIT_MSG_FILE_NAME), "msg-title V {project_version}")

        ret = guess_next_action(ProjectDevVars(project_path=empty_repo_path))

        assert ret == 'commit_project'

        git_commit(empty_repo_path, tst_pkg_version)
        git_checkout(empty_repo_path, DEF_MAIN_BRANCH)
        ensure_tst_ns_portion_version_file(empty_repo_path)
        git_add(empty_repo_path)
        git_commit(empty_repo_path, tst_pkg_version)

        ret = guess_next_action(ProjectDevVars(project_path=empty_repo_path))

        assert ret == 'renew_project'

        # NOT TESTABLE because ret.startswith("¡detached HEAD") if .git gets renamed
        # os.rename(os_path_join(empty_repo_path, ".git"), os_path_join(empty_repo_path, '_renamed_git_folder'))
        #
        # ret = guess_next_action(ProjectDevVars(project_path=empty_repo_path))
        #
        # assert ret.startswith("¡no git workflow initiated")
        # assert "start a new project" in ret
        #
        # os.rename(os_path_join(empty_repo_path, '_renamed_git_folder'), os_path_join(empty_repo_path, ".git"))

        git_checkout(empty_repo_path, new_branch)

        ret = guess_next_action(ProjectDevVars(project_path=empty_repo_path))

        assert ret == 'push_project'

    def test_guess_next_action_fix_empty_on_local_machine_only(self, empty_repo_path):
        assert guess_next_action(ProjectDevVars(project_path=empty_repo_path)).startswith("¡")

        ensure_tst_ns_portion_version_file(empty_repo_path)
        git_checkout(empty_repo_path, new_branch='new_feature_branch_name_testing_guest_next_action' + now_str(sep="_"))
        write_file(os_path_join(empty_repo_path, COMMIT_MSG_FILE_NAME), "msg-title V {project_version}")
        git_add(empty_repo_path)

        assert guess_next_action(ProjectDevVars(project_path=empty_repo_path)) == 'commit_project'
