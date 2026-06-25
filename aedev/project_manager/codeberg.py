"""
helpers to access codeberg.org via its V1 API
=============================================

Codeberg is based on `Forgejo <https://forgejo.org>`__ (a fork of `Gitea <https://gitea.com>`__) and its API
(documented at `https://codeberg.org/api/swagger`__).

this module is a first start, currently only to allow an initial push of a repo to codeberg.org, used as 2nd mirror.
(similar to GitHub, also not allowing initial pushes of a new repository). the plan is to move all my repositories from
GitLab to Codeberg (and then using GitLab as mirror).

created this module because the Python libraries pygitea (https://github.com/jo-nas/pygitea and
https://github.com/h44z/pygitea) were in 2026 no longer maintained (since ~2019).

another api endpoint example to determine the repo url:
    url = f'https://codeberg.org/api/v1/repos/{user_or_org_name}/{repo_name}'
    response = requests.get(url, headers={"Authorization": f"token {token}", "Accept": "application/json"}, timeout=10)
    if response.status_code == 200:
        return response.json()['clone_url']

"""
import time
from collections.abc import Mapping
from typing import TypedDict

import requests

from ae.base import now_str                                                                         # type: ignore
from ae.shell import mask_token                                                                     # type: ignore


API_URL_PREFIX = "https://codeberg.org/api/v1/"


class _RequestsKwargs(TypedDict, total=False):
    """ type of the used arguments of the requests package methods (get/patch/post/..). """
    headers: Mapping[str, str]
    timeout: float | tuple[float, float]


def _headers(token: str) -> Mapping[str, str]:
    """ compile the standard header fields to be sent to codeberg (with authentication token).

    :param token:               private access token of the pushing user.
    :return:                    header fields mapping.
    """
    return {'Authorization': f"token {token}",
            'Content-Type': "application/json",
            'Accept': "application/json", }


def ensure_repo(user_or_group_name: str, repo_name: str, token: str, desc: str = "", private: bool = False) -> str:
    """ check if the repository exists for the specified user or organisation/group and create it if it doesn't.

    :param user_or_group_name:  name of the codeberg user or organisation/repo-group.
    :param repo_name:           name of the repository/project.
    :param token:               personell access token of the pushing user.
    :param desc:                optional repo description.
    :param private:             pass True to make the repository private.
    :return:                    error message if repo is not accessible or could not be created, else empty string.
    """
    api_url = API_URL_PREFIX + f"orgs/{user_or_group_name}/repos"
    timeout = 24.6  # ->doubled: HTTPSConnectionPool(host='codeberg.org', port=443): Read timed out. (read timeout=12.3)
    payload = {'name': repo_name,
               'description': desc or f"{repo_name} created {now_str()} via API by aedev-project-manager",
               'auto_init': False,  # has to be False to not create Readme.md and git history
               'private': private,
               # 'default_branch': main_branch,  # Forgejo/Gitea fails to set this before the initial upload is finished
               }
    headers = _headers(token)

    try:
        res = requests.post(api_url, json=payload, headers=headers, timeout=timeout)

        match res.status_code:
            case 201 | 409:                 # 201==new/initial repo created; 409==repo already exists
                err_str = ""
            case 401:
                err_str = f"authentication error at {api_url=} with token {mask_token(token)}"
            case 403:
                err_str = f"missing 'write:repository' right for organisation '{user_or_group_name}' at {api_url=}"
            case 404:                       # group/organisation name not found - then retry with username
                api_url = API_URL_PREFIX + "user/repos"
                res = requests.post(api_url, json=payload, headers=headers, timeout=timeout)
                err_str = "" if res.status_code in (201, 409) else f"{user_or_group_name=} does not exist at {api_url=}"
            case _:
                err_str = f"{api_url=} returned unexpected status {res.status_code}; response={mask_token(res.text)}"

    except (requests.exceptions.RequestException, Exception) as ex:     # pylint: disable=broad-exception-caught
        err_str = f"POST to {api_url=} raised unexpected exception {mask_token(str(ex))}"

    return err_str


def set_main_branch(user_or_group_name: str, repo_name: str, token: str, main_branch: str, timeout: float = 69.) -> str:
    """ wait until the initial post/upload got finished to set the main/default branch.

    :param user_or_group_name:  name of the codeberg user or organisation/repo-group.
    :param repo_name:           name of the repository/project.
    :param token:               personell access token of the pushing user.
    :param main_branch:         name of the main branch.
    :param timeout:             optional timeout (default is 69 seconds).
    :return:                    error message if default branch could not set, else an empty string.
    """
    api_url = f"{API_URL_PREFIX}/repos/{user_or_group_name}/{repo_name}"
    headers = _headers(token)
    next_call_wait = timeout / 9.9
    deadline = time.time() + timeout
    errors = []
    while time.time() < deadline:
        requests_kwargs: _RequestsKwargs = {"headers": headers, 'timeout': (next_call_wait / 3., next_call_wait)}
        try:
            if not (empty := requests.get(api_url, **requests_kwargs).json().get('empty', "unset")):
                requests.patch(api_url, json={'default_branch': main_branch}, **requests_kwargs).raise_for_status()
                return ""
            errors.append(f"repository {empty=}")

        except requests.exceptions.Timeout as exception:
            errors.append(f"timeout {exception=}; {next_call_wait=}")

        except requests.ConnectionError as exception:
            errors.append(f"connect {exception=}")

        except Exception as exception:                                  # pylint: disable=broad-exception-caught
            errors.append(f"response state {exception=}")

        time.sleep(next_call_wait / 3.)
        next_call_wait *= 3.

    return f"reached {deadline=} in setting {main_branch=} for repository {user_or_group_name}/{repo_name}; {errors=}"
