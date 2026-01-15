""" codeberg.py unit tests. """
from unittest.mock import Mock, patch

from aedev.project_manager.codeberg import ensure_repo


CODEBERG_TOKEN_PART = 'eb309be099'  # UPDATE after token renewal (needed because codeberg lacks to have token prefix)


class TestHelpers:
    def test_ensure_repo(self):
        with patch('requests.post', return_value=Mock(status_code=201)):
            assert ensure_repo("user_or_group_name", "repo_name", "token") == ""

        with patch('requests.post', return_value=Mock(status_code=409)):
            assert ensure_repo("user_or_group_name", "repo_name", "token") == ""

        def _post(url, *_args, **_kwargs):
            if '/orgs/' in url:
                return Mock(status_code=404)
            return Mock(status_code=201)

        with patch('requests.post', new=_post):
            assert ensure_repo("user_or_group_name", "repo_name", "token") == ""

    def test_ensure_repo_invalid_args(self):
        err_msg = ensure_repo("not_existing_user_or_group_name", "not_existing_repo_name", "invalid_token")
        assert isinstance(err_msg, str)
        assert err_msg != ""

    def test_ensure_repo_fails_with_401(self):
        with patch('requests.post', return_value=Mock(status_code=401)):
            assert ensure_repo("user_or_group_name", "repo_name", "token") != ""

    def test_ensure_repo_fails_with_403(self):
        with patch('requests.post', return_value=Mock(status_code=403)):
            assert ensure_repo("user_or_group_name", "repo_name", "token") != ""

    def test_ensure_repo_fails_with_exception(self):
        def _post(url, *_args, **_kwargs):
            raise Exception()

        with patch('requests.post', return_value=Mock(text='tst_err_msg')):
            assert ensure_repo("user_or_group_name", "repo_name", "token") != ""
            assert 'tst_err_msg' in ensure_repo("user_or_group_name", "repo_name", "token")

    def test_ensure_repo_fails_with_invalid_status(self):
        with patch('requests.post', return_value=Mock(status_code=999, text='tst_error_message')):
            assert 'tst_error_message' in ensure_repo("user_or_group_name", "repo_name", "token")
