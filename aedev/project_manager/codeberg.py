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
import requests

from ae.base import now_str                                                                         # type: ignore
from ae.shell import mask_token                                                                     # type: ignore
from aedev.base import DEF_MAIN_BRANCH                                                              # type: ignore


API_URL_PREFIX = "https://codeberg.org/api/v1/"


# pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-return-statements
def ensure_repo(user_or_group_name: str, repo_name: str, token: str,
                main_branch: str = DEF_MAIN_BRANCH, description: str = "", private: bool = False) -> str:
    """ check if the repository exists for the specified user or organisation/group and create it if it doesn't.

    :param user_or_group_name:  name of the codeberg user or organisation/repo-group.
    :param repo_name:           name of the repository/project.
    :param token:               personell access token of the pushing user.
    :param main_branch:         name of the main branch (defaults to :data:`~aedev.base.DEF_MAIN_BRANCH`).
    :param description:         optional repo description.
    :param private:             pass True to make the repository private.
    :return:                    error message if repo is not accessible or could not be created, else empty string.
    """
    api_url = API_URL_PREFIX + f"orgs/{user_or_group_name}/repos"
    headers = {'Authorization': f"token {token}",
               'Content-Type': "application/json",
               'Accept': "application/json", }
    payload = {'name': repo_name,
               'description': description or f"{repo_name} created {now_str()} via API by aedev-project-manager",
               'auto_init': False,  # has to be False to not create Readme.md and git history
               'private': private,
               'default_branch': main_branch, }

    try:
        response = requests.post(api_url, json=payload, headers=headers, timeout=12.3)

        match response.status_code:
            case 201 | 409:                 # 201==new/initial repo created; 409==repo already exists
                return ""
            case 401:
                return f"authentication error at {api_url=} with token {mask_token(token)}"
            case 403:
                return f"missing 'write:repository' right for organisation '{user_or_group_name}' at {api_url=}"
            case 404:
                api_url = API_URL_PREFIX + "user/repos"
                response = requests.post(api_url, json=payload, headers=headers, timeout=12.3)
                if response.status_code in (201, 409):
                    return ""
                return f"{user_or_group_name=} does not exist at {api_url=}"

        return f"{api_url=} returned unexpected status {response.status_code}; response={mask_token(response.text)}"

    except requests.exceptions.RequestException as ex:
        return f"POST to {api_url=} raised unexpected exception {mask_token(str(ex))}"
