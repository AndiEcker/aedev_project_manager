""" codeberg.py unit tests. """
from unittest.mock import Mock, patch

import requests

from aedev.project_manager.codeberg import ensure_repo, set_main_branch


CODEBERG_TOKEN_PART = 'eb309be099'  # UPDATE after token renewal (needed because codeberg lacks to have token prefix)


class TestHelpers:
    def test_ensure_repo(self):
        def _json() -> dict:
            return {'empty': False}

        with (patch('aedev.project_manager.codeberg.requests.post', return_value=Mock(status_code=201)),
              patch('aedev.project_manager.codeberg.requests.get', return_value=Mock(status_code=200, json=_json)),
              patch('aedev.project_manager.codeberg.requests.patch', return_value=Mock(status_code=200)),):
            assert ensure_repo("user_or_group_name", "repo_name", "token") == ""

        with (patch('aedev.project_manager.codeberg.requests.post', return_value=Mock(status_code=409)),
              patch('aedev.project_manager.codeberg.requests.get', return_value=Mock(status_code=200, json=_json)),
              patch('aedev.project_manager.codeberg.requests.patch', return_value=Mock(status_code=200)),):
            assert ensure_repo("user_or_group_name", "repo_name", "token") == ""

        def _post(url, *_args, **_kwargs):
            if '/orgs/' in url:
                return Mock(status_code=404)
            return Mock(status_code=201)

        with (patch('aedev.project_manager.codeberg.requests.post', new=_post),
              patch('aedev.project_manager.codeberg.requests.get', return_value=Mock(status_code=200, json=_json)),
              patch('aedev.project_manager.codeberg.requests.patch', return_value=Mock(status_code=200)),):
            assert ensure_repo("user_or_group_name", "repo_name", "token") == ""

    def test_ensure_repo_exception_get(self):
        def _raise_err(*_args, **_kwargs):
            raise Exception("simulating requests.post() exception")

        with patch('aedev.project_manager.codeberg.requests.get', new=_raise_err):
            assert ensure_repo("user_or_group_name", "repo_name", "token") != ""

    def test_ensure_repo_exception_post(self):
        def _raise_err(*_args, **_kwargs):
            raise Exception("simulating requests.post() exception")

        with patch('aedev.project_manager.codeberg.requests.post', new=_raise_err):
            assert ensure_repo("user_or_group_name", "repo_name", "token") != ""

    def test_ensure_repo_fails_with_401(self):
        with patch('aedev.project_manager.codeberg.requests.post', return_value=Mock(status_code=401)):
            assert ensure_repo("user_or_group_name", "repo_name", "token") != ""

    def test_ensure_repo_fails_with_403(self):
        with patch('aedev.project_manager.codeberg.requests.post', return_value=Mock(status_code=403)):
            assert ensure_repo("user_or_group_name", "repo_name", "token") != ""

    def test_ensure_repo_fails_with_exception(self):
        # def _post(_url, *_args, **_kwargs):
        #    raise Exception()
        with patch('aedev.project_manager.codeberg.requests.post', return_value=Mock(text='tst_err_msg')):
            assert ensure_repo("user_or_group_name", "repo_name", "token") != ""
            assert 'tst_err_msg' in ensure_repo("user_or_group_name", "repo_name", "token")

    def test_ensure_repo_fails_with_invalid_status(self):
        with patch('aedev.project_manager.codeberg.requests.post',
                   return_value=Mock(status_code=999, text='tst_error_message')):
            assert 'tst_error_message' in ensure_repo("user_or_group_name", "repo_name", "token")

    def test_ensure_repo_invalid_args(self):
        err_msg = ensure_repo("not_existing_user_or_group_name", "not_existing_repo_name", "invalid_token")
        assert isinstance(err_msg, str)
        assert err_msg != ""

    def test_ensure_repo_user_or_group_not_exists(self):
        with patch('aedev.project_manager.codeberg.requests.post', return_value=Mock(status_code=404)):
            assert ensure_repo("not_existing_user_or_group_name", "not_existing_repo_name", "invalid_token")

    def test_set_main_branch(self):
        with (patch('aedev.project_manager.codeberg.requests.get', return_value=Mock(json=lambda: {'empty': False})),
              patch('aedev.project_manager.codeberg.requests.patch') as requests_patch_method, ):
            err_msg = set_main_branch("user_or_group_name", "repo_name", "testtoken", "TstBranch", timeout=0.003)
            requests_patch_method.assert_called_once()

        assert isinstance(err_msg, str)
        assert err_msg == ""

    def test_set_main_branch_connect_error(self):
        with patch('aedev.project_manager.codeberg.requests.get', side_effect=requests.ConnectionError("TstConnErr")):
            err_msg = set_main_branch("user_or_group_name", "repo_name", "tst_token_x", "TstBranch", timeout=0.003)

        assert isinstance(err_msg, str)
        assert err_msg != ""

    def test_set_main_branch_empty_repo_error(self):
        with patch('aedev.project_manager.codeberg.requests.get', return_value=Mock(json=lambda: {'empty': True})):
            err_msg = set_main_branch("user_or_group_name", "repo_name", "test_Token", "TestBranch", timeout=0.003)

        assert isinstance(err_msg, str)
        assert err_msg != ""

    def test_set_main_branch_exception_error(self):
        with patch('aedev.project_manager.codeberg.requests.get', side_effect=RuntimeError("testException")):
            err_msg = set_main_branch("user_or_group_name", "repo_name", "tst_token", "TstBranch", timeout=0.003)

        assert isinstance(err_msg, str)
        assert err_msg != ""

    def test_set_main_branch_timeout_error(self):
        with patch('aedev.project_manager.codeberg.time.sleep'):
            err_msg = set_main_branch("user_or_group_name", "repo_name", "Tst_token", "TstBranch", timeout=0.003)

        assert isinstance(err_msg, str)
        assert err_msg != ""

        timeout_message = 'testTimeoutException'
        timeout_exception = requests.exceptions.Timeout(timeout_message)
        with patch('aedev.project_manager.codeberg.requests.get', side_effect=timeout_exception):
            err_msg = set_main_branch("user_or_group_name", "repo_name", "TstToken", "TstBranch", timeout=0.003)

        assert isinstance(err_msg, str)
        assert f"exception=Timeout('{timeout_message}')" in err_msg
