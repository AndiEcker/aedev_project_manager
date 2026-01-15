""" util/helper functions needed by __main__.py and templates.py. """
import os
import pprint
from typing import Any, Collection, Iterable, Optional, Sequence, Union

from github.Repository import Repository
from gitlab.v4.objects import Project
from packaging.version import Version, InvalidVersion

from ae.base import (                                                                                   # type: ignore
    load_env_var_defaults, os_path_isdir, os_path_isfile, os_path_join, read_file, write_file)
from ae.dynamicod import try_call, try_eval                                                             # type: ignore
from ae.managed_files import REFRESHABLE_TEMPLATE_MARKER                                                # type: ignore
from ae.shell import STDERR_BEG_MARKER, STDERR_END_MARKER, get_domain_user_var, sh_exit_if_exec_err     # type: ignore
from aedev.base import PIP_CMD, ROOT_PRJ                                                                # type: ignore
from aedev.commands import (                                                                            # type: ignore
    EXEC_GIT_ERR_PREFIX, GIT_FOLDER_NAME, GIT_RELEASE_REF_PREFIX, GIT_VERSION_TAG_PREFIX, GitRemotesType,
    git_add, git_any, git_branch_remotes, git_current_branch, git_init_if_needed, git_status, git_tag_remotes,
    in_prj_dir_venv)
from aedev.project_vars import (                                                                        # type: ignore
    ChildrenType, ProjectDevVars, frozen_req_file_path, increment_version, latest_remote_version)


# --------------- global constants ------------------------------------------------------------------------------------
ARG_MULTIPLES = ' ...'                                      #: mark multiple args in the :func:`_action` arg_names kwarg
ARG_ALL = 'all'                                             #: `all` argument, for lists, e.g., of namespace portions
ARGS_CHILDREN_DEFAULT = ((ARG_ALL, ), ('children-sets-expr', ), ('children-names' + ARG_MULTIPLES, ))
""" default arguments for children actions. """

DJANGO_EXCLUDED_FROM_CLEANUP = {'db.sqlite', 'project.db', '**/django.mo', 'media/**/*', 'static/**/*'}
""" set of file path masks/pattern to exclude essential files from to be cleaned-up on the server. """

# --------------- global types ----------------------------------------------------------------------------------------
ActionArgs = list[str]                                      #: action arguments specified on pjm command line
ActionArgNames = tuple[tuple[str, ...], ...]
# ActionFunArgs = tuple[ProjectDevVars, str, ...]           # silly mypy does not support tuple with dict, str, ...
# silly mypy: ugly casts needed for ActionSpecification = dict[str, Union[str, ActionArgNames, bool]]
ActionFlags = dict[str, Any]                                #: action flags/kwargs specified on pjm command line

# RegisteredActionValues = Union[bool, str, ActionArgNames, Sequence[str], Callable]
ActionSpec = dict[str, Any]                                 # mypy errors if Any get replaced by RegisteredActionValues
RegisteredActions = dict[str, ActionSpec]

RepoType = Union[Repository, Project]                       #: repo host libs repo object (PyGithub, python-gitlab)

# --------------- global variables - most of them are constant after app initialization/startup -----------------------
PPF = pprint.PrettyPrinter(indent=6, width=189, depth=12).pformat   #: formatter for console printouts

REGISTERED_ACTIONS: RegisteredActions = {}                  #: implemented actions registered via :func:`_action` deco

REGISTERED_HOSTS_CLASS_NAMES: dict[str, str] = {}           #: class names of all supported remote host domains

# --------------- module helpers --------------------------------------------------------------------------------------


def children_desc(pdv: ProjectDevVars, children_pdv: Collection[ProjectDevVars] = ()) -> str:
    """ printable message describing a single child of a namespace root (portion) or of a project parent folder.

    :param pdv:                 project dev vars of the root/parent project.
    :param children_pdv:        project dev vars of the child to get the description for.
    :return:                    description message of the specified namespace-root/parent-folder child.
    """
    namespace_name = pdv['namespace_name']

    ret = f"{len(children_pdv)} " if children_pdv else ""
    ret += f"{namespace_name} portions" if pdv['project_type'] == ROOT_PRJ else "children"

    if children_pdv:
        ns_len = len(namespace_name)
        if ns_len:
            ns_len += 1
        ret += ": " + ", ".join(chi_pdv['project_name'][ns_len:] for chi_pdv in children_pdv)

    return ret


def children_project_names(ini_pdv: ProjectDevVars, names: Sequence[str], chi_vars: ChildrenType) -> list[str]:
    """ check and compile a list of package names of the children of a namespace root or a projects parent folder.

    :param ini_pdv:             project dev variables of a root project or projects parent folder.
    :param names:               names of the
    :param chi_vars:            children project dev variables to double-check and to determine returned list order.
    :return:                    children package names list (ordered in the same order than the specified child pdvs).
    """
    if ini_pdv['project_type'] == ROOT_PRJ:
        assert ini_pdv['namespace_name'], "namespace is not set for ROOT_PRJ"
        pkg_prefix = ini_pdv['namespace_name'] + '_'
        names = [("" if por_name.startswith(pkg_prefix) else pkg_prefix) + por_name for por_name in names]

    if chi_vars:    # return children package names in the same order as in the OrderedDict 'children_project_vars' var
        ori_names = list(names)
        names = [chi['project_name'] for chi in chi_vars.values() if chi['project_name'] in names]
        assert len(names) == len(ori_names), f"length mismatch {len(names)=}!={len(ori_names)=}: {names=} {ori_names=}"

    return list(names)


def expected_args(act_spec: ActionSpec) -> str:
    """ return a printable message explaining the expected arguments of the specified pjm action.

    :param act_spec:            specification of the action to determine the expected arguments for.
    :return:                    printable message with the expected arguments of the specified action.
    """
    arg_names: ActionArgNames = act_spec.get('arg_names', ())
    msg = " -or- ".join(" ".join(_) for _ in arg_names)

    arg_flags = act_spec.get('flags', {})
    if arg_flags:
        if msg:
            msg += ", followed by "
        msg += "optional flags; default: " + " ".join(_n + '=' + repr(_v) for _n, _v in arg_flags.items())

    return msg


def get_app_option(pdv: ProjectDevVars, option_name: str) -> Optional[Any]:
    """ determine command line option value from pdv object.

    :param pdv:                 project dev variables.
    :param option_name:         name of the command line option to determine.
    :return:                    command line option value or None if not found.
    """
    if 'main_app_options' in pdv:
        options = pdv.pdv_val('main_app_options')
        if option_name in options:
            return options[option_name]
    return None


def get_branch(pdv: ProjectDevVars) -> str:
    """ determine name of the branch of the project of the specified pdv object.

    :param pdv:                 project dev variables.
    :return:                    name of the branch specified in the ``--branch`` command line option. if no branch got
                                specified as command line option then return the currently checked-out branch.
    """
    return get_app_option(pdv, 'branch') or git_current_branch(pdv['project_path'])


def get_host_class_name(host_domain: str) -> str:
    """ determine the class name for the specified host domain.

    :param host_domain:         host domain name to determine the corresponding class name.
    :return:                    class name of the specified host domain name or an empty string if no class is found.
    """
    if host_domain in REGISTERED_HOSTS_CLASS_NAMES:
        return REGISTERED_HOSTS_CLASS_NAMES[host_domain]

    host_domain = '.'.join(host_domain.split('.')[-2:])  # to associate eu.pythonanywhere.com with PythonanywhereCom
    if host_domain in REGISTERED_HOSTS_CLASS_NAMES:
        return REGISTERED_HOSTS_CLASS_NAMES[host_domain]

    return ""


def get_host_config_val(pdv: ProjectDevVars, option_name: str, host_domain: str = "", host_user: str = ""
                        ) -> Optional[str]:
    """ determine host/user-specific domain, group, user and token values.

    :param pdv:                 project dev vars with app options and project_path (to include env var values from
                                dotenv files in prj/parent dirs).
    :param option_name:         app option name.
    :param host_domain:         domain name of the host. if not specified or as empty string then the domain specified
                                as command line option (via --repo_domain, --web_domain) will be used. if no option
                                got specified then the search for a host-specific variable will be skipped.
    :param host_user:           username at the host. if not passed or :paramref:`~get_host_config_val.host_domain` is
                                empty, then skip the search for a user-specific variable value.
    :return:                    config variable value or None if not found.
    """
    project_path = pdv['project_path']
    val = get_app_option(pdv, option_name)
    if val is None:
        loaded_env_vars = load_env_var_defaults(project_path, os.environ)
        try:
            if not host_domain:
                pre, *suf = option_name.split('_', maxsplit=1)
                if f"{pre}_" in ('repo_', 'web_') and suf and suf[0] != 'domain':
                    host_domain = get_app_option(pdv, f'{pre}_domain') or ""
            val = get_domain_user_var(option_name, domain=host_domain, user=host_user)
        finally:
            for var_name in loaded_env_vars:
                os.environ.pop(var_name)
    return val


def get_host_domain(pdv: ProjectDevVars, var_prefix: str = 'repo_') -> str:
    """ determine domain name of repository|web host from the repo_domain or web_domain option or config variable.

    :param pdv:                 project dev vars.
    :param var_prefix:          config variable name prefix. pass "web\\_" to get web server host config values.
    :return:                    domain name of repository|web host.
    """
    host_domain = get_host_config_val(pdv, f'{var_prefix}domain')              # 'repo_domain' | 'web_domain'
    if host_domain is None:
        host_domain = pdv[f'{var_prefix}domain']

    # if not get_host_class_name(host_domain):
    #    cae.shutdown(7, error_message=f"unknown {host_domain=}, pass {' or [xx.]'.join(REGISTERED_HOSTS_CLASS_NAMES)}")

    return host_domain


def get_host_group(pdv: ProjectDevVars, host_domain: str) -> str:
    """ determine the upstream user|group name from the --repo_group option or config variable.

    :param pdv:                 project dev vars.
    :param host_domain:         domain to get user token for.
    :return:                    upstream user|group name or, if not found, then the default username PDV_AUTHOR.
    """
    user_group = get_host_config_val(pdv, 'repo_group', host_domain=host_domain)
    if user_group is None:
        user_group = pdv['repo_group'] or pdv['AUTHOR']
    return user_group


def get_host_user_name(pdv: ProjectDevVars, host_domain: str, var_prefix: str = 'repo_') -> str:
    """ determine username from --repo_user/--web_user options, PDV_repo_user or PDV_web_user config variable.

    :param pdv:                 project dev vars.
    :param host_domain:         domain to get user token for.
    :param var_prefix:          config var name prefix.
                                pass 'web\\_' to get web server username. 'repo_user' | 'web_user'
    :return:                    username or if not found the user group name.
    """
    var_name = f'{var_prefix}user'
    user_name = get_host_config_val(pdv, var_name, host_domain=host_domain)
    if user_name is None:
        user_name = pdv[var_name]     # if specified in the env/config variables/file
        if not user_name:
            user_name = get_host_group(pdv, host_domain)
    return user_name


def get_host_user_token(pdv: ProjectDevVars, host_domain: str, host_user: str = "", var_prefix: str = 'repo_') -> str:
    """ determine token or password of user from --repo_token or --web_token option or config variable.

    :param pdv:                 project development variables.
    :param host_domain:         domain to get user token for.
    :param host_user:           host user to get token for.
    :param var_prefix:          config variable name prefix. pass 'web\\_' to get web server host config values.
    :return:                    token string for domain and user on repository|web host.
    """
    var_name = f'{var_prefix}token'
    user_token = get_host_config_val(pdv, var_name, host_domain=host_domain, host_user=host_user)
    if user_token is None:
        user_token = pdv[var_name]     # if specified in the env/config variables/file
    return user_token


def get_mirror_urls(pdv: ProjectDevVars) -> list[str]:
    """ determine the configured mirrors remote names/urls for the project specified by the pdv argument.

    :param pdv:                 project dev vars of the project to determine the mirrors remote-names/urls for.
    :return:                    list of remote-names/urls of the configured mirror urls. the urls that are
                                evaluated to an empty string are not included in this returned list. a empty
                                list will be returned if there are no mirrors configured for the specified project.
    """
    remote_expression = os.environ.get('PJM_MIRROR_REMOTE_EXPRESSIONS')
    if not remote_expression:
        return []

    mirrors = try_eval(remote_expression, glo_vars=pdv.as_dict()) or []
    return [url for url in mirrors if url]


def git_init_add(pdv: ProjectDevVars):
    """ run git add for the project specified by the pdv argument (after running git init if git repo is not created).

    :param pdv:                 project dev vars.
    """
    project_path = pdv['project_path']
    if not git_init_if_needed(project_path, author=pdv['AUTHOR'], email=pdv['AUTHOR_EMAIL']):
        git_add(project_path)


def git_push_url(pdv: ProjectDevVars, authenticate: bool = False, remote_urls: Optional[GitRemotesType] = None) -> str:
    """ determine the origin url of the repository, to push onto. """
    domain = get_host_domain(pdv)
    user_name = get_host_user_name(pdv, domain)

    forked = pdv['REMOTE_UPSTREAM'] in (pdv.pdv_val('remote_urls') if remote_urls is None else remote_urls)
    group_or_user_name = user_name if forked else get_host_group(pdv, domain)

    auth_str = f"{user_name}:{get_host_user_token(pdv, domain, host_user=user_name)}@" if authenticate else ""

    # adding .git extension to repo url prevents 'git fetch --all' redirect warning
    return pdv['REPO_HOST_PROTOCOL'] + auth_str + f"{domain}/{group_or_user_name}/{pdv['project_name']}.git"


# pylint: disable-next=too-many-locals,too-many-branches,too-many-return-statements
def guess_next_action(pdv: ProjectDevVars) -> str:
    """ guess the next action to be done locally.

    :param pdv:                 dev vars of the project.
    :return:                    error message with a "¡" as the first char or one of the action names:
                                'new_project', 'renew_project', 'prepare_commit', 'commit_project', 'push_project',
                                'request_merge', 'release_project'.
    """
    project_path = pdv['project_path']
    project_version = pdv['project_version']
    main_branch = pdv['MAIN_BRANCH']

    if not os_path_isdir(os_path_join(project_path, GIT_FOLDER_NAME)):
        return f"¡no git repository found at {project_path=} ({GIT_FOLDER_NAME} folder is missing)"

    current_branch = git_current_branch(project_path)
    if not current_branch:
        return "¡detached HEAD! - to fix it checkout or create a branch"
    on_main_branch = current_branch == main_branch

    if not project_version or not try_call(Version, project_version, ignored_exceptions=(InvalidVersion, Exception)):
        return f"¡empty or invalid project version '{project_version}'! check the {pdv['version_file']=}"
    prj_ver_obj = Version(project_version)
    if prj_ver_obj < Version(remote_version := latest_remote_version(pdv, increment_part=0)):
        return (f"¡project version discrepancy; local {project_version=} is less than the current {remote_version=};"
                f" run 'pjm renew' to renew/recalculate the next project version")
    if prj_ver_obj > Version(next_remote_version := increment_version(remote_version)):
        return (f"¡project version discrepancy; local {project_version=} is greater than the {next_remote_version=};"
                f" run 'pjm renew' to renew/recalculate the next project version")

    uncommitted = git_status(project_path)
    if uncommitted:
        if on_main_branch:
            return (f"¡detected {main_branch=} with added/changed/uncommitted files: {', '.join(uncommitted)}!"
                    " run 'pjm -b feature_branch renew' to create branch")

        output = git_any(project_path, 'diff', '--staged', '--quiet')   # git_diff() has conflicting options
        if output and output[0].startswith(EXEC_GIT_ERR_PREFIX):    # has exit-code==1 if all changes will be committed
            file_path = os_path_join(project_path, pdv['COMMIT_MSG_FILE_NAME'])
            return 'commit_project' if os_path_isfile(file_path) and '{project_version}' in read_file(file_path) else \
                'prepare_commit'

        return "¡unstaged files found! run git add, or delete them: " + ", ".join(uncommitted)

    if on_main_branch:
        # no git workflow initiated. execute 'pjm -b new_feature_branch renew' to start a new git workflow for an
        # already existing project, or 'pjm new <project type>' to start a new project
        return 'renew_project' if os_path_isdir(os_path_join(project_path, GIT_FOLDER_NAME)) else 'new_project'

    remote_urls = pdv.pdv_val('remote_urls')
    branch_remotes = git_branch_remotes(project_path, current_branch, remote_names=remote_urls)
    version_remotes = git_tag_remotes(project_path, GIT_VERSION_TAG_PREFIX + project_version, remote_names=remote_urls)
    release_remotes = git_branch_remotes(project_path, GIT_RELEASE_REF_PREFIX + project_version,
                                         remote_names=remote_urls)
    if not branch_remotes:
        if version_remotes or release_remotes:
            return (f"¡current branch '{current_branch}' not on remotes, although the current {project_version=}"
                    f" exists on {version_remotes=}/{release_remotes=}!")
        return 'push_project'

    if not version_remotes:
        return f"¡the {project_version=} got not pushed to any remote!"
    if (ori_nam := pdv['REMOTE_ORIGIN']) not in version_remotes:
        return f"¡the origin remote '{ori_nam}' has no {project_version=} tag! tag found only in {version_remotes=}"
    if any(remote not in version_remotes for remote in release_remotes):
        return (f"¡the release remotes {[remote for remote in release_remotes if remote not in version_remotes]}"
                f" are not in {version_remotes=}")
    if release_remotes:
        return f"¡git workflow fully completed for {project_version=}! run pjm -b branch_name renew to start a new one"

    remote_api = pdv.pdv_val('host_api')
    if remote_api is not None and hasattr(remote_api, 'branch_merge_requests'):
        merge_requests = remote_api.branch_merge_requests(pdv, current_branch)
    else:
        merge_requests = []
    if len(merge_requests) > 1 and pdv['REMOTE_UPSTREAM'] in remote_urls:  # multiple MRs and forked
        return f"¡multiple merge requests found for {current_branch=} {merge_requests=}"

    return 'release_project' if merge_requests else 'request_merge'


def ppp(output: Iterable[str]) -> str:
    """ pretty printing formatter function.

    :param output:              output iterable to format for pretty printing.
    :return:                    pretty printing formatted string.
    """
    sep = (os.linesep + "      ") if output else ""
    return sep + sep.join(str(_) for _ in (output.items() if isinstance(output, dict) else output))


def update_frozen_req_files(pdv: ProjectDevVars) -> list[str]:
    """ update the four possible frozen requirements files of a project.

    :param pdv:                 project dev variables of the project to update.
    :return:                    list of errors or an empty list.
    """
    req_file_name = pdv['REQ_FILE_NAME']
    req_file_paths = (
        req_file_name,
        pdv['REQ_DEV_FILE_NAME'],
        os_path_join(pdv['DOCS_FOLDER'], req_file_name),
        os_path_join(pdv['TESTS_FOLDER'], req_file_name),
    )

    errors = []
    with in_prj_dir_venv(pdv['project_path']):
        for req_file_path in req_file_paths:
            errors += update_frozen_req_file(req_file_path, all_packages=req_file_path == pdv['REQ_DEV_FILE_NAME'])

    # update pdv['dev_requires'] with new (frozen) requirements w/o error checking like done by _refresh_pdv/_get_pdv()
    pdv.update(ProjectDevVars(project_path=pdv['project_path'], namespace_name=pdv['namespace_name']))

    return errors


def update_frozen_req_file(req_file_path: str, all_packages: bool = False) -> list[str]:
    """ update frozen requirements file

    :param req_file_path:       file path of the requirements file.
    :param all_packages:        pass True to include also not explicitly requested packages (added by pip freeze).
    :return:                    list of errors or an empty list.
    """
    if not (frozen_file_path := frozen_req_file_path(req_file_path, strict=True)):
        return []

    out_lines: list[str] = []
    sh_exit_if_exec_err(73, PIP_CMD, extra_args=("freeze", "-r", req_file_path), lines_output=out_lines)

    errors: list[str] = []
    if out_lines and out_lines[-1] == STDERR_END_MARKER:
        line_no = len(out_lines) - 2
        while out_lines[line_no] != STDERR_BEG_MARKER:
            errors.insert(0, out_lines[line_no])
            line_no -= 1
    if errors:
        return errors

    line_count = len(read_file(req_file_path).split(os.linesep))
    if not all_packages:
        out_lines = out_lines[:line_count]
    for line, req in enumerate(out_lines):
        if req.startswith("-e "):
            prj_name = req.rsplit('=', maxsplit=1)[-1]
            prj_path = os_path_join("..", prj_name)
            if os_path_isdir(prj_path):
                prj_pdv = ProjectDevVars(project_path=prj_path)
                version = prj_pdv['project_version']
                out_lines[line] = f"{prj_name}=={version}  # {req}"

    if REFRESHABLE_TEMPLATE_MARKER in out_lines[0]:
        out_lines = out_lines[1:]
    file_content = os.linesep.join(out_lines)
    if not all_packages:
        file_content = file_content.replace("## The following requirements were added by pip freeze:", "")

    write_file(frozen_file_path, file_content)

    return []


def write_commit_message(pdv: ProjectDevVars, pkg_version: str = "{project_version}", title: str = ""):
    """ write the commit message file used by git commands.

    :param pdv:                 project dev variables.
    :param pkg_version:         package/project version placeholder.
    :param title:               commit message title.
    """
    sep = os.linesep
    project_path = pdv['project_path']
    file_name = os_path_join(project_path, pdv['COMMIT_MSG_FILE_NAME'])
    if not title:
        title = git_current_branch(project_path).replace("_", " ")
    write_file(file_name, f"{pdv['VERSION_TAG_PREFIX']}{pkg_version}: {title}{sep}{sep}"
                          f"{sep.join(git_status(project_path))}{sep}")
