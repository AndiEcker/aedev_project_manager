""" util/helper functions needed by __main__.py and templates.py. """
import ast
import json
import os
import pprint
import sys
from collections.abc import Collection, Iterable
from os import makedirs as patchable_makedirs
from typing import Any, cast
from unittest.mock import patch

from github.Repository import Repository
from gitlab.v4.objects import Project
from packaging.version import Version, InvalidVersion

from ae.base import (                                                                                   # type: ignore
    DOCS_FOLDER, PY_EXT, PY_INIT, TESTS_FOLDER,
    in_wd, os_path_dirname, os_path_isdir, os_path_isfile, os_path_join, os_path_relpath, read_file, write_file)
from ae.base import write_file as patchable_write_file                     # pylint: disable=reimported # type: ignore
from ae.system import (                                                                                 # type: ignore
    PYPI_PACKAGE_NAMES, load_env_var_defaults, norm_pip_name, project_main_file, PyMo)
from ae.paths import path_files                                                                         # type: ignore
from ae.dynamicod import try_call, try_eval                                                             # type: ignore
from ae.managed_files import REFRESHABLE_TEMPLATE_MARKER                                                # type: ignore
from ae.console import ConsoleApp                                                                       # type: ignore
from ae.shell import (                                                                                  # type: ignore
    STDERR_BEG_MARKER, STDERR_END_MARKER, debug_or_verbose, get_domain_user_var, sh_exit_if_exec_err)
from aedev.base import (                                                                                # type: ignore
    APP_PRJ, DJANGO_PRJ, PIP_CMD, PLAYGROUND_PRJ, PROJECT_VERSION_SEP, ROOT_PRJ, VERSION_PREFIX, VERSION_QUOTE)
from aedev.commands import (                                                                            # type: ignore
    EXEC_GIT_ERR_PREFIX, GIT_FOLDER_NAME, GIT_RELEASE_REF_PREFIX, GIT_VERSION_TAG_PREFIX, GitRemotesType,
    git_add, git_any, git_branch_remotes, git_current_branch, git_init_if_needed, git_status, git_tag_remotes,
    in_prj_dir_venv, venv_module_var_val)
from aedev.project_vars import (                                                                        # type: ignore
    ChildrenType, ProjectDevVars, frozen_req_file_path, increment_version, latest_remote_version, main_file_path)


# --------------- global constants ------------------------------------------------------------------------------------
ARG_MULTIPLES = ' ...'                                      #: mark multiple args in the :func:`_action` arg_names kwarg
ARG_ALL = 'all'                                             #: `all` argument, for lists, e.g., of namespace portions
ARGS_CHILDREN_DEFAULT = ((ARG_ALL, ), ('children-sets-expr', ), ('children-names' + ARG_MULTIPLES, ))
""" default arguments for children actions. """

DJANGO_EXCLUDED_FROM_CLEANUP = {'db.sqlite', 'project.db', '**/django.mo', 'media/**/*', 'static/**/*'}
""" set of file path masks/pattern to exclude essential files from to be cleaned-up on the server. """

PIP_FREEZE_COMMENT = '## The following requirements were added by pip freeze:'
""" console output line of pip freeze command, separating the listed from the additional/unlisted packages. """

# --------------- global types ----------------------------------------------------------------------------------------
ActionArgs = list[str]                                      #: action arguments specified on pjm command line
ActionArgNames = tuple[tuple[str, ...], ...]
# ActionFunArgs = tuple[ProjectDevVars, str, ...]           # silly mypy does not support tuple with dict, str, ...
# silly mypy: ugly casts needed for ActionSpecification = dict[str, str | ActionArgNames, bool]
ActionFlags = dict[str, Any]                                #: action flags/kwargs specified on pjm command line

# RegisteredActionValues = bool | str | ActionArgNames | Sequence[str] | Callable
ActionSpec = dict[str, Any]                                 # mypy errors if Any get replaced by RegisteredActionValues
RegisteredActions = dict[str, ActionSpec]

RepoType = Repository | Project                             #: repo host libs repo object (PyGithub, python-gitlab)

# --------------- global variables - most of them are constant after app initialization/startup -----------------------
PPF = pprint.PrettyPrinter(indent=6, width=189, depth=12).pformat   #: formatter for console printouts

REGISTERED_ACTIONS: RegisteredActions = {}                  #: implemented actions registered via :func:`_action` deco

REGISTERED_HOSTS_CLASS_NAMES: dict[str, str] = {}           #: class names of all supported remote host domains

# --------------- module helpers --------------------------------------------------------------------------------------


def check_folders_files_completeness(cae: ConsoleApp, pdv: ProjectDevVars):
    """ create or renew project folders/files while protocolling any changes to the console.

    :param cae:                 main app instance.
    :param pdv:                 project dev variables.
    """
    changes: list[tuple] = []

    # __name__ == 'aedev.project_manager.utils'
    with (patch(f"{__name__}." + 'patchable_write_file', new=lambda _fn, *_, **__: changes.append(('wf', _fn, _, __))),
          patch(f"{__name__}." + 'patchable_makedirs', new=lambda _dir: changes.append(('md', _dir)))):
        renew_project_dir(pdv)

    if changes:
        cae.po(f"  --  missing {len(changes)} basic project folders/files:")
        if cae.verbose:
            cae.po(PPF(changes))
            cae.po(f"   -- use the 'new_{pdv['project_type']}' action to re-new/complete/update this project")
        else:
            project_path = pdv['project_path']
            for change in changes:
                cae.po(f"    - {change[0] == 'md' and 'folder' or 'file  '} {os_path_relpath(change[1], project_path)}")
    elif debug_or_verbose(cae):                                                             # pragma: no cover
        cae.po("    = project folders and files are complete")


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


def children_project_names(ini_pdv: ProjectDevVars, names: Collection[str], chi_vars: ChildrenType) -> list[str]:
    """ check and compile a list of package names of the children of a namespace root or a projects parent folder.

    :param ini_pdv:             project dev variables of a root project or projects parent folder.
    :param names:               names of the children.
    :param chi_vars:            children project dev variables to double-check and to determine returned list order.
    :return:                    children package names list (ordered in the same order as the specified child pdvs).
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


def code_file_imports(file_path: str, *filter_roots: str) -> set[str] | str:
    """ determines the external/not-builtin module names imported by the specified code file.

    :param file_path:           code file path.
    :param filter_roots:        root names/namespaces of the modules to be ignored/skipped/NOT-returned.
    :return:                    set of filtered/external import/module names, imported by the specified code file,
                                or an error message if the code file could not be parsed.
    """
    imp_modules = imported_modules(file_path)
    if isinstance(imp_modules, str):
        return imp_modules

    ignore_roots = set(sys.builtin_module_names)
    if hasattr(sys, 'stdlib_module_names'):  # Python 3.10+ has also sys.stdlib_module_names
        ignore_roots.update(sys.stdlib_module_names)
    ignore_roots.update(set(filter_roots))

    ext_modules = set()
    for imp_name in imp_modules:
        if not any(imp_name == root or imp_name.startswith(root + '.') for root in ignore_roots):
            ext_modules.add(imp_name)

    return ext_modules


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


def get_app_option(pdv: ProjectDevVars, option_name: str) -> Any | None:
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
                        ) -> str | None:
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
    # noinspection GrazieInspection
    """ determine domain name of repository|web host from the repo_domain or web_domain option or config variable.

    :param pdv:                 project dev vars.
    :param var_prefix:          config variable name prefix. pass 'web\\_' to get web server host config values.
    :return:                    domain name of the host, or an empty string if '{var_prefix}domain' is not set.
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
    :return:                    upstream user|group name or, if not found, then the default username PDV_AUTHOR,
                                and if neither 'repo_group' nor 'AUTHOR' exists then an empty string..
    """
    user_group = get_host_config_val(pdv, 'repo_group', host_domain=host_domain)
    if user_group is None:
        user_group = pdv['repo_group'] or pdv['AUTHOR']
    return user_group


def get_host_user_name(pdv: ProjectDevVars, host_domain: str, var_prefix: str = 'repo_') -> str:
    # noinspection GrazieInspection
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
    # noinspection GrazieInspection
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
                                evaluated to an empty string are not included in this returned list. an empty
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


def git_push_url(pdv: ProjectDevVars, authenticate: bool = False, remote_urls: GitRemotesType | None = None) -> str:
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
    :return:                    error message with a '¡' as the first char or one of the action names:
                                'new_project', 'renew_project', 'prepare_commit', 'commit_project', 'push_project',
                                'request_merge', 'release_project'.
    """
    project_path = pdv['project_path']
    project_version = pdv['project_version']
    main_branch = pdv['MAIN_BRANCH']
    prefix = '¡'

    if not os_path_isdir(os_path_join(project_path, GIT_FOLDER_NAME)):
        return f"{prefix}no git repository found at {project_path=} ({GIT_FOLDER_NAME} folder is missing)"

    current_branch = git_current_branch(project_path)
    if not current_branch:
        return f"{prefix}detached HEAD! - to fix it checkout or create a branch"
    on_main_branch = current_branch == main_branch

    if not project_version or not try_call(Version, project_version, ignored_exceptions=(InvalidVersion, Exception)):
        return f"{prefix}empty or invalid project version '{project_version}'! check the {pdv['version_file']=}"
    prj_ver_obj = Version(project_version)
    if prj_ver_obj < Version(remote_version := latest_remote_version(pdv, increment_part=0)):
        return (f"{prefix}project version discrepancy; local {project_version=} is less than the {remote_version=};"
                f" run 'pjm renew' to renew/recalculate the next project version")
    if prj_ver_obj > Version(next_remote_version := increment_version(remote_version)):
        return (f"{prefix}project version discrepancy; local {project_version=} is greater than {next_remote_version=};"
                f" run 'pjm renew' to renew/recalculate the next project version")

    uncommitted = git_status(project_path)
    if uncommitted:
        if on_main_branch:
            return (f"{prefix}detected {main_branch=} with added/changed/uncommitted files: {', '.join(uncommitted)}!"
                    " run 'pjm -b feature_branch renew' to create branch")

        output = git_any(project_path, 'diff', '--staged', '--quiet')   # git_diff() has conflicting options
        if output and output[0].startswith(EXEC_GIT_ERR_PREFIX):    # has exit-code==1 if all changes will be committed
            file_path = os_path_join(project_path, pdv['COMMIT_MSG_FILE_NAME'])
            return 'commit_project' if os_path_isfile(file_path) and '{project_version}' in read_file(file_path) else \
                'prepare_commit'

        return f"{prefix}unstaged files found! run git add, or delete them: " + ", ".join(uncommitted)

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
            return (f"{prefix}current branch '{current_branch}' not on remotes, although the current {project_version=}"
                    f" exists on {version_remotes=}/{release_remotes=}!")
        return 'push_project'

    if not version_remotes:
        return f"{prefix}the {project_version=} got not pushed to any remote!"
    if (ori_nam := pdv['REMOTE_ORIGIN']) not in version_remotes:
        return f"{prefix}the origin remote '{ori_nam}' has no {project_version=} tag! tag found in {version_remotes=}"
    if any(remote not in version_remotes for remote in release_remotes):
        return (f"{prefix}the release remotes {[remote for remote in release_remotes if remote not in version_remotes]}"
                f" are not in {version_remotes=}")
    if release_remotes:
        return f"{prefix}git workflow completed for {project_version=}! run `pjm -b <branch> renew` to start a new one"

    merge_requests = []
    remote_api = pdv.pdv_val('host_api')
    if remote_api is not None and hasattr(remote_api, 'branch_merge_requests'):
        merge_requests = remote_api.branch_merge_requests(pdv, current_branch)
        if len(merge_requests) > 1 and pdv['REMOTE_UPSTREAM'] in remote_urls:  # multiple MRs and forked
            return f"{prefix}multiple merge requests found for {current_branch=} {merge_requests=}"

    return 'release_project' if merge_requests else 'request_merge'


def import_dependencies(cae: ConsoleApp, project_path: str, project_type: str, import_name: str
                        ) -> set[str]:   # pragma: no cover
    """ determine the import dependencies of all the package/project code files.

    :param cae:                 main app instance.
    :param project_path:        project root path.
    :param project_type:        project type.
    :param import_name:         project import name.
    :return:                    set of imported package/project names.
    """
    import_deps: set[str] = set()
    for code_file in package_code_files(project_path):
        deps_or_err = code_file_imports(os_path_join(project_path, code_file), import_name)
        cae.chk(23, no_err := isinstance(deps_or_err, set), cast(str, deps_or_err))
        if no_err:
            import_deps.update(deps_or_err)

    if project_type == DJANGO_PRJ:
        if dj_deps := venv_module_var_val(import_name + '.settings', 'INSTALLED_APPS', cwd=project_path,
                                          validator=lambda _val: isinstance(_val, list)):
            # noinspection PyTypeChecker
            import_deps.update(set(dj_deps))
            cae.dpo(f"   !! project imports/dependencies: {import_deps}")
        else:
            cae.po(f"   ## Django apps dependencies NOT found at {project_path}/{import_name}/settings.py;  {dj_deps=}")

    return import_deps


def imported_modules(code_file_path: str) -> set[str] | str:
    """ determines the module names imported by the specified code file.

    :param code_file_path:      code file path.
    :return:                    set of import/module names (imported by the specified code file),
                                or an error message if the code file could not be parsed.
    """
    module_names = set()
    try:
        tree = ast.parse(read_file(code_file_path), filename=code_file_path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):  # import os, sys, pandas, x.y
                for alias in node.names:
                    module_names.add(alias.name)
            elif isinstance(node, ast.ImportFrom):  # from x import y; level==0 for absolute imports (not from .x)
                if node.level == 0 and node.module:
                    module_names.add(node.module)
    except (AttributeError, IndentationError, MemoryError, OSError, SyntaxError, SystemError) as ex:
        return f"parsing of {code_file_path=} for imported modules raised {ex=}"

    return module_names


def installed_packages(cae: ConsoleApp, project_path: str) -> list[str]:    # pragma: no cover
    """ determine the installed pip packages from the local project repository/root and its Python environment.

    :param cae:                 main app instance.
    :param project_path:        project root path.
    :return:                    list of installed pip packages/projects names.
    """
    installed: list[str] = []
    with in_prj_dir_venv(project_path=project_path):
        sh_exit_if_exec_err(24, PIP_CMD, extra_args=("list", "--format=json"), lines_output=installed, shell=True)
    cae.vpo(f"    ! installed pip packages (in json format): {installed}")
    installed = [norm_pip_name(_['name']) for _ in json.loads(installed[0])]
    cae.dpo(f"   !! installed pip packages: {installed}")
    return installed


def missing_imports(cae: ConsoleApp, import_deps: set[str], project_reqs: list[str], ignore_extra_reqs: list[str]
                    ) -> tuple[list[str], set[str]]:   # pragma: no cover
    """ determine pip package names that are required but not explicitly imported by a project.

    :param cae:                 main app instance.
    :param import_deps:         set of imported package/project names (determinable by :func:`import_dependencies`).
    :param project_reqs:        list of external package/project names, required by the project.
    :param ignore_extra_reqs:   list of packages names that will be returned in the returned as ignored.
    :return:                    tuple of missing and missing&ignored import names.
    """
    import_names = {norm_pip_name(_pip_name): _imp_name for _imp_name, _pip_name in PYPI_PACKAGE_NAMES.items()}
    cae.vpo(f"    ! irregular PyPI project names (not convertable from their import names): {import_names}")
    # from itertools import accumulate
    # norm_deps={_pe for _dep in deps for _pe in accumulate(_dep.replace('_', '-').split('.'), lambda x, y: f"{x}-{y}")}
    perm_deps = set()
    for _dep_names in import_deps:
        _parts = _dep_names.replace('_', '-').split('.')
        for i in range(1, len(_parts) + 1):
            perm_deps.add('-'.join(_parts[:i]))
    cae.vpo(f"    ! permutations of dependencies import names: {perm_deps}")
    ignoring_reqs = [norm_pip_name(_pip_name) for _pip_name in ignore_extra_reqs]
    cae.dpo(f"   !! ignored required PyPI projects that are not explicitly imported: {ignoring_reqs}")
    ignored_reqs = set()
    missed_imports = []
    for req_pkg in project_reqs:
        if req_pkg in import_names:
            req_pkg = import_names[req_pkg]
        if req_pkg not in perm_deps:
            if req_pkg in ignoring_reqs:
                ignored_reqs.add(req_pkg)
            else:
                missed_imports.append(req_pkg)

    return missed_imports, ignored_reqs


# pylint: disable=too-many-arguments,too-many-positional-arguments
def missing_requirements(cae: ConsoleApp, project_path: str, import_deps: set[str], venv_packages: list[str],
                         project_reqs: list[str], ignoring_imports: list[str]
                         ) -> tuple[list[str], list[str], set[str]]:    # pragma: no cover
    """ determine the import names of a local project repository that are not explicitly required.

    :param cae:                 main app instance.
    :param project_path:        root path of the local project repository.
    :param import_deps:         set of imported package/project names (determinable by :func:`import_dependencies`).
    :param venv_packages:       list of installed pip packages/projects names (returned by :func:`installed_packages`).
    :param project_reqs:        list of external package/project names, required by the project.
    :param ignoring_imports:    list of external package/project import names that will be returned as missing&ignored.
    :return:                    tuple with 3 items containing missing package/project import names partitioned as:
                                (1) not required, (2) not installed in VENV (3) not required but ignored.
    """
    norm_pip_names = {_imp_name: norm_pip_name(_pip_name) for _imp_name, _pip_name in PYPI_PACKAGE_NAMES.items()}
    cae.vpo(f"    ! ignoring imports: {ignoring_imports}")
    missing_reqs = []
    uninstalled_packages: list[str] = []
    ignored_imports = set()

    def _in_packages(_packages: list[str], current_imp_names: list[str], current_pip_name: str) -> bool:
        return any(
            norm_pip_name(_n) in _packages
            or os_path_isfile(os_path_join(project_path, _n.replace('.', "/") + PY_EXT))
            or os_path_isfile(os_path_join(project_path, _n.replace('.', "/"), PY_INIT))
            or norm_pip_names.get(_n, current_pip_name) in _packages
            for _n in current_imp_names)

    for imp_path in import_deps:
        mod_obj = PyMo(imp_path)

        name_parts = mod_obj.name_parts
        imp_names = ['.'.join(name_parts[:i]) for i in range(1, len(name_parts) + 1)]

        if not _in_packages(project_reqs, imp_names, mod_obj.pip_name):
            if imp_path in ignoring_imports:
                ignored_imports.add(imp_path)
            else:
                missing_reqs.append(imp_path)

        if not _in_packages(venv_packages, imp_names, mod_obj.pip_name):
            uninstalled_packages.append(imp_path)

    return missing_reqs, uninstalled_packages, ignored_imports


def package_code_files(prj_root_path: str) -> set[str]:
    """ determines the package code files present in the specified project root path.

    :param prj_root_path:       project root path.
    :return:                    set of package code files present in the specified project root path.
    """
    with in_wd(prj_root_path):
        code_files = path_files("**/*" + PY_EXT)
    return {_ for _ in code_files if not _.startswith((DOCS_FOLDER + "/", TESTS_FOLDER + "/"))}


def ppp(output: Iterable[str]) -> str:
    """ pretty printing formatter function.

    :param output:              output iterable to format for pretty printing.
    :return:                    pretty printing formatted string.
    """
    sep = (os.linesep + "      ") if output else ""
    return sep + sep.join(str(_) for _ in (output.items() if isinstance(output, dict) else output))


def project_topics(pdv: ProjectDevVars) -> list[str]:
    """ extracts the project topics of a project.

    :param pdv:                 project development variables.
    :return:                    list of the project topics.
    """
    topic_marker = 'Topic :: '      # set in :meth:`aedev_project_vars.ProjectDevVars._compile_setup_kwargs`
    for classifier in pdv.pdv_val('setup_kwargs')['classifiers']:
        if classifier.startswith(topic_marker):
            return classifier[len(topic_marker):].split(' :: ')
    return []


def refresh_pdv(pdv: ProjectDevVars):
    """ refresh pdv in-place to reflect the current state of the project working tree.

    :param pdv:                 project development variables.
    """
    pdv.update(ProjectDevVars(project_path=pdv['project_path'], namespace_name=pdv['namespace_name']))


def renew_project_dir(pdv: ProjectDevVars):     # pylint: disable=too-many-branches
    """ create&complete a project or check&protocol which files and subfolders are missing.

    .. note:: to check&protocol patch :func:`patchable_makedirs` and :func:`patchable_write_file` and log their calls.

    :param pdv:                 project development variables.
    """
    namespace_name = pdv['namespace_name']
    project_name = pdv['project_name']
    project_path = pdv['project_path']
    project_type = pdv['project_type']

    is_root = project_type == ROOT_PRJ
    import_name = namespace_name + '.' + project_name[len(namespace_name) + 1:] if namespace_name else project_name
    sep = os.linesep

    if not os_path_isdir(project_path):
        patchable_makedirs(project_path)  # needed for check_folders_files_completeness(), _renew_project() does it too

    file_name = os_path_join(project_path, pdv['REQ_FILE_NAME'])
    if not os_path_isfile(file_name):
        patchable_write_file(file_name, f"# runtime dependencies of the {import_name} project")

    main_file = project_main_file(import_name, project_path=project_path)
    if not main_file:
        main_file = main_file_path(project_path, project_type, namespace_name=namespace_name)
        main_path = os_path_dirname(main_file)
        if not os_path_isdir(main_path):
            patchable_makedirs(main_path)
    if not os_path_isfile(main_file):
        patchable_write_file(main_file, f"\"\"\" {project_name} {project_type} main module \"\"\"{sep}"
                                        f"{sep}"
                                        f"{VERSION_PREFIX}{pdv['NULL_VERSION']}{VERSION_QUOTE}{sep}")

    if project_type == PLAYGROUND_PRJ:
        return

    if not namespace_name or is_root:
        sub_dir = os_path_join(project_path, pdv['DOCS_FOLDER'])
        if not os_path_isdir(sub_dir):
            patchable_makedirs(sub_dir)

    if is_root:
        sub_dir = os_path_join(pdv['package_path'], pdv['TEMPLATES_FOLDER'])
        if not os_path_isdir(sub_dir):
            patchable_makedirs(sub_dir)

    sub_dir = os_path_join(project_path, pdv['TESTS_FOLDER'])
    if not os_path_isdir(sub_dir):
        patchable_makedirs(sub_dir)

    if project_type == APP_PRJ:
        file_name = os_path_join(project_path, pdv['APP_BUILD_CFG_FILENAME'])
        if not os_path_isfile(file_name):
            patchable_write_file(file_name, f"# {REFRESHABLE_TEMPLATE_MARKER}{sep}[app]{sep}")

    if project_type == DJANGO_PRJ:
        file_name = os_path_join(project_path, 'manage.py')
        if not os_path_isfile(file_name):
            patchable_write_file(file_name, f"# {REFRESHABLE_TEMPLATE_MARKER}{sep}")


def update_frozen_req_file(project_pip_name: str, req_file_path: str, all_packages: bool = False,
                           integrate_pip_errors: bool = False) -> list[str]:
    """ update frozen requirements file

    :param project_pip_name:    pip name of the project with this requirements file.
    :param req_file_path:       file path of the requirements file.
    :param all_packages:        pass True to include also not explicitly requested packages (added by pip freeze).
    :param integrate_pip_errors: pass True to integrate errors into the resulting frozen requirements file.
    :return:                    an empty list (if :paramref:`update_rozen_req_file.integrate_pip_errors` is True)
                                or a list of pip error output lines.
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
        if not integrate_pip_errors:
            return errors
        out_lines = out_lines[:-(len(errors) + 2)]

    if not all_packages:
        # out_lines = out_lines[:1 + len([_ for _ in read_file(req_file_path).splitlines() if _.strip()])]
        # pylint: disable-next=consider-using-with,unspecified-encoding
        out_lines = out_lines[:1 + sum(1 for _line in open(req_file_path) if _line.strip()) - len(errors)]
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
    out_lines = (["# " + _ for _ in errors] +
                 [_ for _ in out_lines if not _.replace('_', '-').startswith(project_pip_name + PROJECT_VERSION_SEP)])
    file_content = os.linesep.join(out_lines)
    if not all_packages:
        file_content = file_content.replace(PIP_FREEZE_COMMENT, "")

    write_file(frozen_file_path, file_content)

    return []


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
        pip_name = pdv['pip_name']
        dev_req_file_path = pdv['REQ_DEV_FILE_NAME']
        for req_file_path in req_file_paths:
            errors += update_frozen_req_file(pip_name, req_file_path, all_packages=req_file_path == dev_req_file_path)

    # update pdv['dev_requires'] with new (frozen) requirements w/o error checking like done by _refresh_pdv/_get_pdv()
    refresh_pdv(pdv)

    return errors


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
