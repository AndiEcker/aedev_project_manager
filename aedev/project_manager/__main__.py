"""
Python Project Manager
======================


constants, classes and helper functions
---------------------------------------

this main module of the project-manager tool implements the CLI including the supported dev-ops (actions)

the classes :class:`GithubCom` and :class:`GitlabCom` are providing access to the related
repository hosting services and the :class:`PythonanywhereCom` to check and deploy web apps.

helper functions like :func:`web_app_version` determining the remote version of a deployed django app project package.

constants and types are declared in this module and in the project-internal :mod:`~aedev.project_manager.utils`,
like e.g. :data:`~aedev.project_manager.utils.PPF` and :mod:`~aedev.project_manager.utils.pprint` providing
consistent indented console outputs via pretty print formatters.



external helpers dependencies
-----------------------------

helper functions to categorize and maintain project attributes are provided by the two external
module :mod:`aedev.commands` and :mod:`aedev.project_vars`, portions of the ``aedev`` namespace.
helper functions provided by the :mod:`aedev.commands` encapsulate ``git`` and ``pip`` commands.
:func:`~aedev.project_vars.increment_version`, :func:`~aedev.project_vars.latest_remote_version` or
:func:`~aedev.project_vars.replace_file_version` are used by this module to determine or manipulate
the local/remote/released versions of your projects.

the ``ae`` namespace portion :mod:`ae.managed_files` provides the base functionality
(e.g., :func:`~ae.managed_files.deploy_template` and :func:`~ae.managed_files.patch_string`),
extended by the helpers provided by the project-internal module :mod:`~aedev.project_manager.templates`,
to generate managed project files from the `aedev.*_tpls` template projects
(like e.g. :mod:`aedev.project_tpls` or :mod:`aedev.app_tpls`). example implementations can be found .e.g.
in the :func:`add_file` action and in the functions :func:`~aedev.project_manager.templates.check_templates`
and :func:`~ae.managed_files.deploy_template`.

the portion :mod:`ae.pythonanywhere` portion encapsulates the web API to deploy Django web applications
to the Pythonanywhere webserver.
"""
# pylint: disable=too-many-lines
import ast
import datetime
import glob
import os
import re
import shutil
import time

from collections import OrderedDict
from fnmatch import fnmatch
from functools import partial, wraps
from os import makedirs as patchable_makedirs
from traceback import format_exc
from typing import TYPE_CHECKING, Any, Callable, Container, Optional, Union, cast
from unittest.mock import patch
from urllib.parse import urlparse

from github import Auth, Github, GithubException, UnknownObjectException
from github.AuthenticatedUser import AuthenticatedUser
from github.Organization import Organization
from github.Repository import Repository

from gitlab import Gitlab, GitlabAuthenticationError, GitlabCreateError, GitlabError, GitlabHttpError, GitlabListError
from gitlab.const import MAINTAINER_ACCESS
from gitlab.v4.objects import Group, Project, ProjectMergeRequest, User

from packaging.version import Version, InvalidVersion
from PIL import Image


from ae.base import (  # type: ignore # pylint: disable=reimported
    PY_INIT, UNSET, UnsetType,
    camel_to_snake, duplicates, module_attr, norm_name, norm_path, now_str, on_ci_host,
    os_path_dirname, os_path_isdir, os_path_isfile, os_path_join,
    os_path_relpath, os_path_splitext,
    project_main_file, read_file, stack_var, url_failure, write_file,
    write_file as patchable_write_file, os_path_basename)
from ae.files import FileObject                                                                         # type: ignore
from ae.paths import (                                                                                  # type: ignore
    FilesRegister,
    copy_file, move_file, paths_match, relative_file_paths, skip_py_cache_files)
from ae.dynamicod import try_call, try_eval                                                             # type: ignore
from ae.literal import Literal                                                                          # type: ignore
from ae.updater import MOVES_SRC_FOLDER_NAME, UPDATER_ARGS_SEP, UPDATER_ARG_OS_PLATFORM                 # type: ignore
from ae.core import DEBUG_LEVEL_DISABLED, temp_context_cleanup                                          # type: ignore
from ae.console import ConsoleApp                                                                       # type: ignore
from ae.shell import debug_or_verbose                                                                   # type: ignore
from ae.managed_files import REFRESHABLE_TEMPLATE_MARKER, deploy_template                               # type: ignore
from ae.pythonanywhere import PythonanywhereApi                                                         # type: ignore
from aedev.base import (                                                                                # type: ignore
    ALL_PRJ_TYPES, ANY_PRJ_TYPE, APP_PRJ, DJANGO_PRJ, MODULE_PRJ, NO_PRJ, PACKAGE_PRJ, PARENT_PRJ,
    PIP_CMD, PIP_INSTALL_CMD, PROJECT_VERSION_SEP, VERSION_PREFIX, VERSION_QUOTE,
    code_version, get_pypi_versions, project_name_version)
from aedev.commands import (                                                                            # type: ignore
    EXEC_GIT_ERR_PREFIX, GIT_CLONE_CACHE_CONTEXT, GIT_FOLDER_NAME,
    bytes_file_diff, check_commit_msg_file,
    git_any, git_branches, git_branch_files, git_branch_remotes, git_checkout, git_clone, git_commit,
    git_current_branch, git_diff, git_fetch, git_init_if_needed, git_merge, git_push, git_renew_remotes,
    git_status, git_tag_add, git_ref_in_branch, git_tag_list, git_tag_remotes, git_uncommitted,
    hint, in_os_env, in_prj_dir_venv, mask_token, owner_project_from_url,
    sh_exit_if_exec_err, sh_exit_if_git_err, sh_log, sh_logs)
from aedev.project_vars import (                                                                        # type: ignore
    PDV_docs_domain, PDV_repo_domain, PLAYGROUND_PRJ, ROOT_PRJ,
    ChildrenType,
    increment_version, latest_remote_version, main_file_path, project_owner_name_version,
    replace_file_version, root_packages_masks, skip_files_lean_web,
    ProjectDevVars)


from aedev.project_manager.codeberg import ensure_repo
from aedev.project_manager.templates import (
    PATH_PREFIXES_PARSERS, TPL_IMPORT_NAMES,
    check_templates, project_templates, template_path_option, template_version_option)
from aedev.project_manager.utils import (
    ARG_ALL, ARGS_CHILDREN_DEFAULT, ARG_MULTIPLES, DJANGO_EXCLUDED_FROM_CLEANUP, PPF,
    REGISTERED_ACTIONS, REGISTERED_HOSTS_CLASS_NAMES,
    ActionArgs, ActionFlags, ActionSpec, RepoType,
    children_desc, children_project_names, expected_args, get_app_option, get_branch,
    get_host_class_name, get_host_domain, get_host_group, get_host_user_name, get_host_user_token,
    get_mirror_urls,
    git_init_add, git_push_url, guess_next_action, ppp, update_frozen_req_files, write_commit_message)


# pylint: disable-next=invalid-name
cae = cast(ConsoleApp, cast(object, None))    #: main app instance of this pjm tool, initialized by :func:`init_main`


def _action(*project_types: str, **deco_kwargs) -> Callable:     # Callable[[Callable], Callable]:
    """ parametrized decorator to declare functions and :class:`RemoteHost` methods as `pjm` actions. """
    if not project_types:
        project_types = ALL_PRJ_TYPES

    def _deco(fun):
        # global REGISTERED_ACTIONS
        method_of = stack_var('__qualname__')

        if 'local_action' not in deco_kwargs:
            deco_kwargs['local_action'] = not method_of
        if project_types == (PARENT_PRJ, ROOT_PRJ) and 'arg_names' not in deco_kwargs:
            deco_kwargs['arg_names'] = ARGS_CHILDREN_DEFAULT

        sep = os.linesep
        doc_str = sep.join(_ for _ in fun.__doc__.split(sep)
                           if ':param ini_pdv:' not in _ and ':return:' not in _ and _.strip())

        full_name = (method_of + "." if method_of else "") + fun.__name__
        REGISTERED_ACTIONS[full_name] = {'full_name': full_name, 'annotations': fun.__annotations__,
                                         'docstring': doc_str, 'project_types': project_types, **deco_kwargs}

        @wraps(fun)
        def _wrapped(*fun_args, **fun_kwargs):  # fun_args==(self, ) for remote action methods and ==() for functions
            return fun(*fun_args, **fun_kwargs)
        return _wrapped

    return _deco


def _act_callable(host_api: Optional["RemoteHost"], act_name: str) -> Optional[Callable]:
    return globals().get(act_name) or getattr(host_api, act_name, None)


def _act_help_print(spec: ActionSpec, indent: int = 9):
    ind = " " * indent
    sep = os.linesep

    cae.po(f"{ind}{spec['full_name']}: " + (sep + ind).join(_ for _ in spec['docstring'].split(sep)))

    if 'arg_names' in spec or 'flags' in spec:
        cae.po(f"{ind}- args/flags: {expected_args(spec)}")

    cae.po(f"{ind}- project types: {', '.join(_ for _ in spec['project_types'] if _)}")

    if 'shortcut' in spec:
        cae.po(f"{ind}- shortcut: {spec['shortcut']}")


def _act_spec(pdv: ProjectDevVars, act_name: str) -> tuple[dict[str, Any], str]:   # ActionSpecification
    for reg_name, reg_spec in REGISTERED_ACTIONS.items():   # pylint: disable=too-many-nested-blocks
        if reg_name == act_name:
            return reg_spec, 'repo_'
        if reg_name.endswith(f'.{act_name}'):
            for var_prefix in ('repo_', 'web_'):
                host_domain = get_host_domain(pdv, var_prefix=var_prefix)
                if host_domain:
                    cls_name = get_host_class_name(host_domain)
                    if cls_name and var_prefix == getattr(globals().get(cls_name, None), 'var_prefix', ""):
                        key_name = f"{cls_name}.{act_name}"
                        if key_name == reg_name:
                            return reg_spec, var_prefix

    return {'local_action': True}, '?¿?'  # action isn't found; return pseudo action spec to display an error later


def _act_specs(act_name: str) -> list[ActionSpec]:
    act_specs = []
    for qual_name in [act_name] + [_ + "." + act_name for _ in REGISTERED_HOSTS_CLASS_NAMES.values()]:
        if qual_name in REGISTERED_ACTIONS:
            act_specs.append(REGISTERED_ACTIONS[qual_name])
    return act_specs


def _available_actions(project_type: Union[UnsetType, str] = UNSET) -> set[str]:
    return set(name.split(".")[-1] for name, data in REGISTERED_ACTIONS.items()
               if project_type is UNSET or project_type in data['project_types'])


def _check_action(pdv: ProjectDevVars, *acceptable_actions: Callable):
    action_names = [action.__name__ for action in acceptable_actions]
    action_desc = (f"the '{action_names[0]}' action" if len(acceptable_actions) == 1 else
                   f"one of the actions {action_names}")
    guessed_action = guess_next_action(pdv)
    has_discrepancy = guessed_action.startswith("¡")

    cae.chk(13, not has_discrepancy,
            f"found discrepancy (while checking the execution of {action_desc}):\n" + " " * 6 + guessed_action[1:])
    if not has_discrepancy:
        cae.chk(13, guessed_action in action_names, f"expected '{guessed_action}' instead of {action_desc}" + hint(
            'pjm', _act_callable(pdv.pdv_val('host_api'), guessed_action) or guessed_action, " to follow the workflow"))


def _check_and_add_version_tag(pdv: ProjectDevVars) -> str:
    increment_part = cast(int, get_app_option(pdv, 'versionIncrementPart'))
    project_path = pdv['project_path']
    local_ver = pdv['project_version']
    cae.chk(75, try_call(Version, local_ver, ignored_exceptions=(InvalidVersion, )),
            f"local project version '{local_ver}' has invalid format not conform to PEP 440")

    if git_tag_list(project_path, tag_pattern=pdv['VERSION_TAG_PREFIX'] + "*"):  # not the first/initial project version
        next_version = latest_remote_version(pdv, increment_part=increment_part)
        version_match = _check_version(next_version) == _check_version(local_ver)
        cae.chk(77, version_match, f"version mismatch: local={local_ver} next-remote={next_version}")

    tag = pdv['VERSION_TAG_PREFIX'] + local_ver
    errors = git_tag_add(project_path, tag, commit_msg_file=pdv['COMMIT_MSG_FILE_NAME'])
    cae.chk(79, not bool(errors), f"error in adding the git {tag=}:{ppp(errors)}")

    return tag


def _check_folders_files_completeness(pdv: ProjectDevVars):
    changes: list[tuple] = []

    with (patch(__name__ + '.patchable_write_file', new=lambda _fn, *_, **__: changes.append(('wf', _fn, _, __))),
          patch(__name__ + '.patchable_makedirs', new=lambda _dir: changes.append(('md', _dir)))):
        _renew_prj_dir(pdv)

    if changes:
        cae.po(f"  --  missing {len(changes)} basic project folders/files:")
        if cae.verbose:
            cae.po(PPF(changes))
            cae.po(f"   -- use the 'new_{pdv['project_type']}' action to re-new/complete/update this project")
        else:
            project_path = pdv['project_path']
            for change in changes:
                cae.po(f"    - {change[0] == 'md' and 'folder' or 'file  '} {os_path_relpath(change[1], project_path)}")
    elif debug_or_verbose():
        cae.po("    = project folders and files are complete")


def _check_children_not_exist(parent_or_root_pdv: ProjectDevVars, *project_versions: str):
    prj_path = parent_or_root_pdv['project_path']
    parent_path = prj_path if parent_or_root_pdv['project_type'] == PARENT_PRJ else os_path_dirname(prj_path)
    for pkg_and_ver in project_versions:
        project_path = os_path_join(parent_path, pkg_and_ver.split(PROJECT_VERSION_SEP)[0])
        cae.chk(12, not os_path_isdir(project_path), f"project path {project_path} does already exist")


def _check_children_to_clone(parent_root_sister_pdv: ProjectDevVars, *project_owner_name_versions: str):
    root_or_sister = parent_root_sister_pdv['project_type'] != PARENT_PRJ
    group = get_app_option(parent_root_sister_pdv, 'repo_group') or ""
    def_grp = group or root_or_sister and parent_root_sister_pdv['repo_group'] or ""
    nsn = get_app_option(parent_root_sister_pdv, 'namespace_name') or ""
    def_nsn = nsn or root_or_sister and parent_root_sister_pdv['namespace_name']
    branch = get_app_option(parent_root_sister_pdv, 'branch') or ""

    prj_names = []
    for own_prj_ver in project_owner_name_versions:
        own, prj, ver = project_owner_name_version(own_prj_ver, owner_default=def_grp, namespace_default=def_nsn)
        prj_names.append(prj)

        cae.chk(58, prj.startswith(nsn), f"namespace-name-prefix {nsn} mismatch for specified portion '{own_prj_ver}'")
        cae.chk(58, own == group or not own or not group, f"project owner mismatch: --repo_group {group} != {own}")
        cae.chk(58, ver == branch or not ver or not branch, f"branch to clone mismatch: --branch {branch} != {ver}")

    _check_children_not_exist(parent_root_sister_pdv, *prj_names)


def _check_resources_img(pdv: ProjectDevVars) -> list[str]:
    """ check images, message texts and sounds of the specified project. """
    local_images = FilesRegister(os_path_join(pdv['project_path'], "img", "**"))
    for name, files in local_images.items():
        dup_files = duplicates(norm_path(str(file)) for file in files)
        cae.chk(69, not dup_files, f"duplicate image file paths for '{name}': {dup_files}")

    file_names: list[str] = []
    for name, files in local_images.items():
        file_names.extend(norm_path(str(file)) for file in files)
    dup_files = duplicates(file_names)
    cae.chk(69, not dup_files, f"image resources file paths duplicates: {dup_files}")

    for name, files in local_images.items():
        for file_name in (norm_path(str(file)) for file in files):
            cae.chk(69, bool(read_file(file_name, extra_mode='b')), f"empty image resource in {file_name}")
            # noinspection PyBroadException
            try:
                img = Image.open(file_name)
                img.verify()
            except Exception as ex:                                 # pylint: disable=broad-exception-caught
                cae.chk(69, False, f"Pillow/PIL detected corrupt image {file_name=} {ex=}")

    if debug_or_verbose():
        cae.po(f"    = passed checks of {len(local_images)} image resources ({len(file_names)} files: {file_names})")

    return list(local_images.values())


def _check_resources_i18n_ae(file_name: str, content: str):
    """ check a translation text file with ae_i18n portion message texts.

    :param file_name:           message texts file name.
    :param content:             message texts file content.
    """
    eval_texts = try_eval(content, ignored_exceptions=(Exception, ))
    texts = ast.literal_eval(content)
    cae.chk(69, eval_texts == texts, f"eval and literal_eval results differ in {file_name}")
    cae.chk(69, isinstance(texts, dict), f"no dict literal in {file_name}, got {type(texts)}")
    for key, text in texts.items():
        cae.chk(69, isinstance(key, str), f"file content dict keys must be strings, but got {type(key)}")
        cae.chk(69, isinstance(text, (str, dict)), f"dict values must be str|dict, got {type(text)}")
        if isinstance(text, dict):
            for sub_key, sub_txt in text.items():
                cae.chk(69, isinstance(sub_key, str), f"sub-dict-keys must be strings, got {type(sub_key)}")
                typ = float if sub_key in ('app_flow_delay', 'fade_out_app', 'next_page_delay',
                                           'page_update_delay', 'tour_start_delay', 'tour_exit_delay') else str
                cae.chk(69, isinstance(sub_txt, typ), f"sub-dict-values of {sub_key} must be {typ}")


def _check_resources_i18n_po(file_name: str, content: str):
    """ check a translation text file with GNU gettext message texts.

    :param file_name:           message texts file name (.po file).
    :param content:             message texts file content.
    """
    native = '/en/' in file_name
    mo_file_name = os_path_splitext(file_name)[0] + '.mo'
    cae.chk(69, os_path_isfile(mo_file_name), f"missing compiled message file {mo_file_name}")
    if not on_ci_host():    # skip this check on CI host because the unpacked/installed mo/po file dates are not correct
        po_date = datetime.datetime.fromtimestamp(os.path.getmtime(file_name))
        mo_date = datetime.datetime.fromtimestamp(os.path.getmtime(mo_file_name))
        cae.chk(69, native or po_date <= mo_date, f"{file_name} ({po_date}) not compiled into .mo ({mo_date})")

    id_marker = "msgid"
    str_marker = "msgstr"
    in_txt = msg_id = msg_str = ""
    in_header = True
    for lno, text in enumerate(content.split(os.linesep), start=1):
        in_id = in_txt.startswith(id_marker)
        if text.startswith(id_marker):
            cae.chk(69, not in_txt, f"new {id_marker} in uncompleted {in_txt} in {file_name=}:{lno=}")
            cae.chk(69, not msg_id, f"duplicate {id_marker} in {file_name=}:{lno=}")
            cae.chk(69, text[len(id_marker) + 1] == text[-1] == '"', f"missing \" in {text} in {file_name=}:{lno=}")
            msg_id = text[len(id_marker) + 2:-1]
            cae.chk(69, in_header or msg_id != "", f"missing header or empty {id_marker} text in {file_name=}:{lno=}")
            in_txt = text
        elif text.startswith(str_marker):
            cae.chk(69, text[len(str_marker) + 1] == text[-1] == '"', f"missing \" in {text} in {file_name=}:{lno=}")
            cae.chk(69, in_header or bool(msg_id and in_id), f"{str_marker} w/o {id_marker} in {file_name=}:{lno=}")
            msg_str = text[len(str_marker) + 2:-1]
            in_txt = text
        elif in_txt:
            if text:
                cae.chk(69, text[0] == text[-1] == '"', f"misplaced \" in multiline {in_txt=} in {file_name=}:{lno=}")
                if in_id:
                    msg_id += text[1:-1]
                else:       # in_txt.startswith(str_marker)
                    msg_str += text[1:-1]
                in_txt += ".."
            else:
                cae.chk(69, in_header or msg_id != "", f"empty id text in {file_name=}:{lno=}")
                if debug_or_verbose() and not native and not msg_str:
                    cae.po(f"    # ignoring empty translation of \"{msg_id}\" in {file_name=}:{lno=}")
                in_txt = msg_id = msg_str = ""
                in_header = False
        else:
            cae.chk(69, not text or text[0] == "#", f"expected comment/empty-line, got {text} in {file_name=}:{lno=}")


def _check_resources_i18n_texts(pdv: ProjectDevVars) -> list[str]:
    def _chk_files(chk_func: Callable[[str, str], None], *path_parts: str) -> list[FileObject]:
        stem_mask = path_parts[-1]
        regs = FilesRegister(os_path_join(pdv['project_path'], *path_parts))
        file_names: list[str] = []
        for stem_name, files in regs.items():
            for file_name in (norm_path(str(file)) for file in files):
                content = read_file(file_name)
                cae.chk(69, bool(content), f"stem {stem_name} has empty translation message file {file_name}")
                chk_func(file_name, content)
                file_names.append(file_name)

        dup_files = duplicates(file_names)
        cae.chk(69, not dup_files, f"file paths duplicates of {stem_mask} translations: {dup_files}")

        if debug_or_verbose():
            cae.po(f"    = passed checks of {len(regs)} {stem_mask} (with {len(file_names)} files: {file_names})")

        return list(regs.values())

    return (_chk_files(_check_resources_i18n_ae, "loc", "**", "**Msg.txt") +
            _chk_files(_check_resources_i18n_po, "**", "locale", "**", "django.po"))


def _check_resources_snd(pdv: ProjectDevVars) -> list[str]:
    local_sounds = FilesRegister(os_path_join(pdv['project_path'], "snd", "**"))

    for name, files in local_sounds.items():
        dup_files = duplicates(norm_path(str(file)) for file in files)
        cae.chk(69, not dup_files, f"duplicate sound file paths for '{name}': {dup_files}")

    file_names: list[str] = []
    for name, files in local_sounds.items():
        file_names.extend(norm_path(str(file)) for file in files)
    dup_files = duplicates(file_names)
    cae.chk(69, not dup_files, f"sound resources file paths duplicates: {dup_files}")

    for name, files in local_sounds.items():
        for file_name in (norm_path(str(file)) for file in files):
            cae.chk(69, bool(read_file(file_name, extra_mode='b')), f"empty sound resource in {file_name}")

    if debug_or_verbose():
        cae.po(f"    = passed checks of {len(local_sounds)} sound resources ({len(file_names)} files: {file_names})")

    return list(local_sounds.values())


def _check_resources(pdv: ProjectDevVars):
    """ check images, message texts and sounds of the specified project. """
    resources = _check_resources_img(pdv) + _check_resources_i18n_texts(pdv) + _check_resources_snd(pdv)
    if resources:
        cae.po(f"  === {len(resources)} image/message-text/sound resources checks passed")
        if debug_or_verbose():
            cae.po(ppp(str(_) for _ in resources)[1:])


def _check_types_linting_tests(pdv: ProjectDevVars):    # pylint: disable=too-many-locals,too-many-statements
    mll = 120   # maximal length of code lines
    namespace_name = pdv['namespace_name']
    project_name = pdv['project_name']
    project_path = pdv['project_path']
    project_type = pdv['project_type']
    project_packages = pdv.pdv_val('project_packages')
    root_packages = [_ for _ in project_packages if '.' not in _]

    excludes = ['migrations' if project_type == DJANGO_PRJ else 'templates']    # folder names to exclude from checks
    path_args = namespace_name and [namespace_name] or root_packages or [pdv['version_file']]

    options = []
    if debug_or_verbose():
        options.append("-v")
        if cae.verbose:
            options.append("-v")
        cae.dpo(f"    - project packages: {ppp(project_packages)}")
        cae.dpo(f"    - project root packages: {ppp(root_packages)}")
        cae.dpo(f"    - command line options: {ppp(options)}")
        cae.dpo(f"    - command line arguments: {ppp(path_args)}")

    with in_prj_dir_venv(project_path):
        extra_args = [f"--max-line-length={mll}"] + ["--exclude=" + _ for _ in excludes] + options + path_args
        sh_exit_if_exec_err(60, "flake8", extra_args=extra_args)

        os.makedirs("mypy_report", exist_ok=True)                   # sh_exit_if_exec_err(61, "mkdir -p ./mypy_report")
        extra_args = ["--exclude=/" + _ + "/" for _ in excludes] + [  # added / and +"/" to not exclude ae/templates.py
            "--lineprecision-report=mypy_report", "--pretty", "--show-absolute-path", "--show-error-codes",
            "--show-error-context", "--show-column-numbers", "--warn-redundant-casts", "--warn-unused-ignores"
        ] + (["--namespace-packages", "--explicit-package-bases"] if namespace_name else []) + options + path_args
        # refactor/extend to the --strict option/level, equivalent to the following:  ( [*] == already used )
        # check-untyped-defs, disallow-any-generics, disallow-incomplete-defs, disallow-subclassing-any,
        # disallow-untyped-calls, disallow-untyped-decorators, disallow-untyped-defs, no-implicit-optional,
        # no-implicit-reexport, strict-equality, warn-redundant-casts [*], warn-return-any, warn-unused-configs,
        # warn-unused-ignores [*], """
        sh_exit_if_exec_err(61, "mypy", extra_args=extra_args)
        sh_exit_if_exec_err(61, "anybadge",
                            extra_args=("--label=MyPy", "--value=passed", "--file=mypy_report/mypy.svg", "-o"))

        os.makedirs(".pylint", exist_ok=True)
        out: list[str] = []
        # disabling false-positive pylint errors E0401(unable to import) and E0611(no name in module) caused by name
        # clash for packages kivy and ae.kivy (see https://github.com/PyCQA/pylint/issues/5226 of user hmc-cs-mdrissi).
        extra_args = [f"--max-line-length={mll}", "--output-format=text", "--recursive=y", "--disable=E0401,E0611"] \
            + ["--ignore=" + _ for _ in excludes] + options + path_args
        # alternatively to exit_on_err=False: using pylint option --exit-zero
        sh_exit_if_exec_err(62, 'pylint', extra_args=extra_args, exit_on_err=False, lines_output=out)
        if get_app_option(pdv, 'more_verbose') and not cae.debug:
            cae.po(ppp(out))
        matcher = re.search(r"Your code has been rated at ([-\d.]*)", os.linesep.join(out))
        cae.chk(62, bool(matcher), f"pylint score search failed in string {os.linesep.join(out)}")
        write_file(os_path_join(".pylint", "pylint.log"), os.linesep.join(out))
        score = matcher.group(1) if matcher else "<undetermined>"
        sh_exit_if_exec_err(62, "anybadge",
                            extra_args=("-o", "--label=Pylint", "--file=.pylint/pylint.svg",  f"--value={score}",
                                        "2=red", "4=orange", "8=yellow", "10=green"))
        cae.po(f"  === pylint score: {score}")

        sub_dir = ".pytest_cache"
        cov_db = ".coverage"
        extra_args = [f"--ignore-glob=**/{_}/*" for _ in excludes] \
            + [f"--cov={_}" for _ in namespace_name and [namespace_name] or root_packages or ["."]] \
            + ["--cov-report=html", "-v"] + options + [pdv['TESTS_FOLDER'] + "/"]
        if not namespace_name or project_type != PACKAGE_PRJ:
            # --doctest-glob="...*.py" does not work for .py files (only collectable via --doctest-modules).
            # doctest fails on namespace packages even with --doctest-ignore-import-errors (modules are ok).
            # actually, pytest doesn't raise an error on namespace-package, but without collecting doctests and only if
            # --doctest-ignore-import-errors get specified and if args (==namespace) got specified after TESTS_FOLDER
            extra_args = ["--doctest-modules"] + extra_args + path_args
        sh_exit_if_exec_err(46, "pytest", extra_args=extra_args)
        db_ok = os_path_isfile(cov_db)
        cae.chk(47, db_ok, f"coverage db file ({cov_db}) not created for tests or doctests in {path_args}")
        os.makedirs(sub_dir, exist_ok=True)
        if db_ok:           # prevent FileNotFoundError exception to allow ignorable fail on forced check run
            os.rename(cov_db, os_path_join(sub_dir, cov_db))

        os.chdir(sub_dir)   # KIS: move .coverage and create coverage.txt/coverage.svg in the .pytest_cache sub-dir
        out = []            # IO fixed: .coverage/COV_CORE_DATAFILE in cwd, txt->stdout
        sh_exit_if_exec_err(48, "coverage report --omit=" + ",".join("*/" + _ + "/*" for _ in excludes),
                            lines_output=out)
        write_file("coverage.txt", os.linesep.join(out))
        sh_exit_if_exec_err(49, "coverage-badge -o coverage.svg -f")
        cov_rep_file = f"{project_path}/htmlcov/{project_name}_py.html"
        if not os_path_isfile(cov_rep_file):
            cov_rep_file = f"{project_path}/htmlcov/index.html"
        cae.po(f"  === pytest coverage: {out[-1][-4:]} - check detailed report in file:///{cov_rep_file}")
        os.chdir("..")


def _check_version(version_number: str, prefix_to_check: str = "") -> str:
    """ check project version, exit the app on any format error, and return the checked version without the prefix. """
    if prefix_to_check:
        prefix_len = len(prefix_to_check)
        if version_number[:prefix_len] != prefix_to_check:
            cae.shutdown(76, error_message=f"{version_number=} is missing the version tag prefix '{prefix_to_check}")
        version_number = version_number[prefix_len:]

    if version_number.count('.') != 2:
        cae.shutdown(76, error_message=f"{version_number=} doas not contain exactly two dot characters")

    try:
        Version(version_number)
    except InvalidVersion as ex:
        cae.shutdown(76, error_message=f"{version_number=} is not conform to PEP 440 ({ex})")

    return version_number


def _get_pdv(**kwargs):
    """ create a pdv instance from the specified kwargs, check it for errors and if it has errors then exit app. """
    pdv = ProjectDevVars(**kwargs)
    errors = pdv.errors()
    cae.chk(8, not errors, f"project development variable discrepancies: {ppp(errors)}")
    return pdv


# pylint: disable-next=too-many-locals,too-many-branches
def _init_act_args_check(ini_pdv: ProjectDevVars, act_spec: Any, act_name: str, act_args: ActionArgs,
                         act_flags: ActionFlags):
    """ check and possibly complete the command line arguments and split optional action flags from action args.

    called after _init_act_exec_args/INI_PDV-initialization.
    """
    cae.dpo(f"   -- args check of action {act_name} ({act_spec.get('docstring', '').split(os.linesep)[0].strip('. ')})")
    cae.vpo(f"    - {act_name} command line {act_args=} and {act_flags=}")

    optional_flags = act_spec.get('flags', {})
    for flag_name, _flag_value in act_flags.items():
        cae.chk(9, flag_name in optional_flags,
                f"invalid command line flag {flag_name} for {act_name} action; expected: {optional_flags.keys()}")

    for flag_name, flag_def in optional_flags.items():
        val_pos, flag_type = len(flag_name) + 1, type(flag_def)
        for act_arg in act_args[:]:
            if (bool_flag := act_arg == flag_name) or act_arg.startswith(flag_name + '='):
                flag_val = True if bool_flag else Literal(act_arg[val_pos:]).value
                cae.chk(9, isinstance(flag_val, flag_type),
                        f"command line flag {flag_name} has invalid type '{type(flag_val)}', expected '{flag_type}'")
                act_flags[flag_name] = flag_val
                act_args.remove(act_arg)
                break
        else:
            act_flags[flag_name] = flag_def

    alt_arg_names = act_spec.get('arg_names', ())
    arg_count = len(act_args)
    if alt_arg_names:
        for arg_names in alt_arg_names:
            pos_names = []
            opt_names = []
            for arg_name in arg_names:
                if arg_name.startswith("--"):
                    opt_names.append(arg_name[2:])
                else:
                    pos_names.append(arg_name)
            pos_cnt = len(pos_names)
            pos_ok = pos_cnt and pos_names[-1].endswith(ARG_MULTIPLES) and pos_cnt <= arg_count or pos_cnt == arg_count
            if pos_ok and all(cae.get_option(opt_name) for opt_name in opt_names):
                break
        else:
            cae.shutdown(9, error_message=f"expected arguments/flags: {expected_args(act_spec)}")
    elif arg_count:
        cae.shutdown(9, error_message=f"no arguments expected, but got {act_args}")

    project_type = ini_pdv['project_type']
    cae.vpo(f"    - detected project type '{project_type}' for project in {ini_pdv['project_path']}")
    if project_type not in act_spec['project_types']:
        cae.shutdown(9, error_message=f"action '{act_name}' only available for: {act_spec['project_types']}")

    cae.dpo("    = passed checks of basic command line options and arguments")


def _init_act_args_shortcut(ini_pdv: ProjectDevVars, ini_act_name: str) -> str:
    project_type = ini_pdv['project_type']
    found_actions: list[str] = []
    for act_name, act_spec in REGISTERED_ACTIONS.items():
        if project_type in act_spec['project_types'] and act_spec.get('shortcut') == ini_act_name:
            found_actions.append(act_name.split(".")[-1])
    count = len(found_actions)
    if not count:
        return ""

    assert count in (1, 2), f"duplicate shortcut declaration for {found_actions}; correct _action() shortcut kwargs"
    if count > 1:   # happens for a namespace-root project type, where action is available for a project and children
        found_actions = sorted(found_actions, key=len)      # 'project'/7 is shorter than 'children'/8
    return found_actions[0]


def _init_act_exec_args() -> tuple[ProjectDevVars, str, tuple, dict[str, Any]]:     # pylint: disable=too-many-locals
    """ prepare execution of an action requested via command line arguments and options.

    * init project dev vars
    * checks if action is implemented
    * check action arguments
    * run optional pre_action.

    :return:                    tuple of project pdv, action name to execute, a tuple with additional action args
                                and a dict of optional action flag arguments.
    """
    ini_pdv = _init_pdv()

    act_name = initial_action = norm_name(cae.get_argument('action'))
    act_args = cae.get_argument('arguments').copy()
    initial_args = act_args.copy()
    project_type = ini_pdv['project_type']
    actions = _available_actions(project_type=project_type)
    while act_name not in actions:
        if not act_args:
            found_act_name = _init_act_args_shortcut(ini_pdv, initial_action)
            if found_act_name:
                act_name = found_act_name
                act_args[:] = initial_args
                break
            prj = ("undefined/new" if project_type is NO_PRJ else project_type) + f" project {ini_pdv['project_path']}"
            cae.shutdown(6, error_message=f"invalid action '{act_name}' for {prj}. valid actions: {actions}")
            return ini_pdv, "request exit of unit test with patched shutdown()", (), {}
        act_name += '_' + norm_name(act_args[0])
        act_args[:] = act_args[1:]

    act_spec, var_prefix = _act_spec(ini_pdv, act_name)
    if not act_spec['local_action']:
        host_domain = ini_pdv[f'{var_prefix}domain']
        ini_pdv['host_api'] = host_api = globals()[get_host_class_name(host_domain)]()
        cae.chk(38, bool(_act_callable(ini_pdv.pdv_val('host_api'), act_name)),
                f"action {act_name} not implemented for {host_domain}")
        if not host_api.connect(ini_pdv):
            cae.po(f" **** connection to {host_domain} remote host server failed")

    act_flags: ActionFlags = {}
    _init_act_args_check(ini_pdv, act_spec, act_name, act_args, act_flags)

    extra_children_args = ""
    extra_msg = ""
    if '_children' in act_name or 'children_pdv' in act_spec['annotations']:
        arg_count = len(act_spec['annotations']) - (2       # ini_pdv
                                                    + (1 if 'return' in act_spec['annotations'] else 0)
                                                    + (1 if 'optional_flags' in act_spec['annotations'] else 0))
        if arg_count:
            extra_children_args = " <" + " ".join(_ for _ in act_args[:arg_count]) + ">"
        act_args[arg_count:] = _init_children_pdv_args(ini_pdv, act_args[arg_count:])
        extra_msg += f" :: {children_desc(ini_pdv, children_pdv=act_args[arg_count:])}"

    pre_action = act_spec.get('pre_action')
    if pre_action:
        cae.po(f" ---- executing pre-action {pre_action.__name__}")
        pre_action(ini_pdv, *act_args)

    cae.po(f"----- {act_name}{extra_children_args} on {ini_pdv['project_title']}{extra_msg}")

    return ini_pdv, act_name, act_args, act_flags


def _init_children_pdv_args(ini_pdv: ProjectDevVars, act_args: ActionArgs) -> list[ProjectDevVars]:
    """ get package names of the portions specified as command line args, optionally filtered by --branch option. """
    chi_vars: ChildrenType = ini_pdv.pdv_val('children_project_vars')

    if act_args == [ARG_ALL]:
        pkg_names = list(chi_vars)
    else:
        chi_presets = _init_children_presets(ini_pdv, chi_vars).copy()
        pkg_names = try_eval(" ".join(act_args), ignored_exceptions=(Exception, ), glo_vars=chi_presets)
        if pkg_names is UNSET:
            pkg_names = children_project_names(ini_pdv, act_args, OrderedDict())
            cae.vpo(f"    # action arguments {act_args} are not evaluable with vars={PPF(chi_presets)}")
        else:
            pkg_names = children_project_names(ini_pdv, pkg_names, chi_vars)

    for preset in ('filterExpression', 'filterBranch'):  # == (preset in presets)
        cae.chk(23, bool(get_app_option(ini_pdv, preset)) == any((preset in _) for _ in act_args),
                f"mismatch of option '{preset}' and its usage in children-sets-expression {' '.join(act_args)}")
    cae.chk(23, len(pkg_names) == len(set(pkg_names)),
            f"{len(pkg_names) - len(set(pkg_names))} duplicate children specified: {duplicates(pkg_names)}")

    if not bool(pkg_names) and isinstance(pkg_names, (list, set, tuple)):
        cae.po(f"  === no children/portions found that are matching the arguments: {act_args}")

    chi_path_dirname = ini_pdv['project_path']
    if ini_pdv['project_type'] != PARENT_PRJ:
        chi_path_dirname = os_path_dirname(chi_path_dirname)
    chi_args = []
    for p_name in pkg_names:
        chi_args.append(chi_vars[p_name] if p_name in chi_vars
                        else _get_pdv(project_path=os_path_join(chi_path_dirname, p_name)))
    return chi_args


def _init_children_presets(ini_pdv: ProjectDevVars, chi_vars: ChildrenType) -> dict[str, set[str]]:
    branch = get_app_option(ini_pdv, 'filterBranch')
    expr = get_app_option(ini_pdv, 'filterExpression')

    chi_ps: dict[str, set[str]] = {}
    ps_all = chi_ps[ARG_ALL] = set()
    ps_edi = chi_ps['editable'] = set()
    ps_mod = chi_ps['modified'] = set()
    ps_dev = chi_ps['develop'] = set()
    if branch:
        chi_ps['filterBranch'] = set()
    if expr:
        chi_ps['filterExpression'] = set()

    for chi_pdv in chi_vars.values():
        project_name, project_path = chi_pdv['project_name'], chi_pdv['project_path']
        current_branch = git_current_branch(project_path)

        ps_all.add(project_name)
        if chi_pdv['editable_project_path']:
            ps_edi.add(project_name)
        if git_uncommitted(project_path):
            ps_mod.add(project_name)
        if current_branch == chi_pdv['MAIN_BRANCH']:
            ps_dev.add(project_name)
        if branch and current_branch == branch:
            chi_ps['filterBranch'].add(project_name)
        if expr:
            glo_vars = globals().copy()
            glo_vars.update(chi_pdv)
            glo_vars['chi_pdv'] = chi_pdv
            with in_prj_dir_venv(project_path):
                result = try_eval(expr, ignored_exceptions=(Exception, ), glo_vars=glo_vars)
            if result:
                chi_ps['filterExpression'].add(project_name)
            elif result == UNSET:
                cae.vpo(f"    # filter expression {expr} not evaluable; glo_vars={PPF(glo_vars)}")

    return chi_ps


def _init_pdv(**overwrite_app_options) -> ProjectDevVars:
    main_app_options = {}
    pdv_options = {}

    for option in cae.cfg_options:
        opt_value = cae.get_option(option)
        if opt_value is not None and opt_value != "":   # 0-values will be recognized
            main_app_options[option] = opt_value
            if option in ('docs_domain', 'namespace_name', 'project_name', 'project_path',
                          'repo_domain', 'repo_group', 'repo_token', 'repo_user',
                          'web_domain', 'web_token', 'web_user'):
                pdv_options[option] = opt_value

    cae.vpo(f"    - command line option defaults: {ppp(main_app_options)}")
    main_app_options.update(overwrite_app_options)
    cae.vpo(f"    - updated command line options: {ppp(main_app_options)}")

    return _get_pdv(main_app_options=main_app_options, **pdv_options)


def _print_pdv(pdv: ProjectDevVars):
    project_type = pdv['project_type']
    namespace = pdv['namespace_name']
    dev_requires = pdv.pdv_val('dev_requires')
    pdv = pdv.copy()

    if not get_app_option(pdv, 'more_verbose'):
        pdv['setup_kwargs'] = skw = (pdv.pdv_val('setup_kwargs') or {}).copy()

        nsp_len = len(namespace) + 1
        if project_type in (PARENT_PRJ, ROOT_PRJ):
            pdv['children_project_vars'] = ", ".join(pdv.pdv_val('children_project_vars'))
        pdv['dev_requires'] = ", ".join(dev_requires)
        pdv['docs_requires'] = ", ".join(pdv.pdv_val('docs_requires'))
        pdv['install_requires'] = ", ".join(pdv.pdv_val('install_requires'))
        if 'long_desc_content' in pdv:
            pdv['long_desc_content'] = skw['long_description'] = pdv['long_desc_content'][:33] + "..."
        pdv['package_data'] = ", ".join(pdv.pdv_val('package_data'))
        pdv['portions_packages'] = ", ".join(pkg[nsp_len:] for pkg in sorted(pdv.pdv_val('portions_packages')))
        pdv['project_packages'] = ", ".join(pdv.pdv_val('project_packages'))
        pdv['tests_requires'] = ", ".join(pdv.pdv_val('tests_requires'))

    if not cae.verbose:
        for name, val in list(pdv.items()):
            if not val or name in (
                    name.upper(), 'children_project_vars', 'dev_requires', 'docs_requires', 'import_name',
                    'install_requires', 'long_desc_content', 'long_desc_type', 'main_app_options', 'namespace_name',
                    'pip_name', 'portion_name', 'portions_packages', 'portions_import_names',
                    'portions_pypi_refs', 'portions_pypi_refs_md', 'portions_project_vars',
                    'project_desc', 'project_id', 'project_name', 'project_packages', 'project_templates',
                    'project_version', 'pypi_url', 'repo_domain', 'repo_group', 'repo_pages', 'repo_root',
                    'setup_kwargs', 'tests_requires', 'version_file', 'web_domain'):
                pdv.pop(name, None)
    elif 'project_templates' not in pdv:
        pdv['project_templates'] = project_templates(project_type, namespace, {}, {}, tuple(dev_requires))

    pdv.pop('repo_token', None)     # never print credentials/token

    cae.po(f"      {PPF(pdv)}")


def _refresh_pdv(pdv: ProjectDevVars, **pdv_kwargs):
    for var_nam in ('main_app_options', 'project_path', 'namespace_name'):
        if var_nam not in pdv_kwargs and var_nam in pdv:
            pdv_kwargs[var_nam] = pdv.pdv_val(var_nam)
    pdv.update(_get_pdv(**pdv_kwargs))


def _renew_prj_dir(new_pdv: ProjectDevVars):
    namespace_name = new_pdv['namespace_name']
    project_name = new_pdv['project_name']
    project_path = new_pdv['project_path']
    project_type = new_pdv['project_type']

    is_root = project_type == ROOT_PRJ
    import_name = namespace_name + '.' + project_name[len(namespace_name) + 1:] if namespace_name else project_name
    sep = os.linesep

    if not os_path_isdir(project_path):
        patchable_makedirs(project_path)  # needed for _check_folders_files_completeness(), _renew_project() does it too

    file_name = os_path_join(project_path, new_pdv['REQ_FILE_NAME'])
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
                                        f"{VERSION_PREFIX}{new_pdv['NULL_VERSION']}{VERSION_QUOTE}{sep}")

    if project_type == PLAYGROUND_PRJ:
        return

    sub_dir = os_path_join(project_path, new_pdv['DOCS_FOLDER'])
    if (not namespace_name or is_root) and not os_path_isdir(sub_dir):
        patchable_makedirs(sub_dir)

    sub_dir = os_path_join(new_pdv['package_path'], new_pdv['TEMPLATES_FOLDER'])
    if is_root and not os_path_isdir(sub_dir):
        patchable_makedirs(sub_dir)

    sub_dir = os_path_join(project_path, new_pdv['TESTS_FOLDER'])
    if not os_path_isdir(sub_dir):
        patchable_makedirs(sub_dir)

    file_name = os_path_join(project_path, new_pdv['BUILD_CONFIG_FILE'])
    if project_type == APP_PRJ and not os_path_isfile(file_name):
        patchable_write_file(file_name, f"# {REFRESHABLE_TEMPLATE_MARKER}{sep}[app]{sep}")

    file_name = os_path_join(project_path, 'manage.py')
    if project_type == DJANGO_PRJ and not os_path_isfile(file_name):
        patchable_write_file(file_name, f"# {REFRESHABLE_TEMPLATE_MARKER}{sep}")


def _renew_project(ini_pdv: ProjectDevVars, project_type: str) -> ProjectDevVars:
    project_path = ini_pdv['project_path']

    if not os_path_isdir(project_path):
        os.makedirs(project_path)
        cae.po(f"    - created project root folder {project_path}")

    remote_urls = ini_pdv.pdv_val('remote_urls')

    if project_type != ini_pdv['project_type']:
        cae.vpo(f"    # overwriting default project type '{ini_pdv['project_type']} with the requested {project_type=}")
        _refresh_pdv(ini_pdv, project_type=project_type, remote_urls=remote_urls)

    new_repo = git_init_if_needed(project_path)
    action = "created new" if new_repo else "renewed"

    renew_branch = get_app_option(ini_pdv, 'branch')
    main_branch = ini_pdv['MAIN_BRANCH']
    if renew_branch or git_current_branch(project_path) == main_branch:
        if not renew_branch or renew_branch == main_branch:
            renew_branch = f"{norm_name(action)}_{project_type}_{ini_pdv['project_name']}_{now_str()}"
        co_args = ("--merge", "--track") \
            if f"remotes/{ini_pdv['REMOTE_ORIGIN']}/{renew_branch}" in git_branches(project_path) else ()
        git_checkout(project_path, *co_args, new_branch=renew_branch, force=bool(get_app_option(ini_pdv, 'force')),
                     remote_names=remote_urls)

    if not new_repo:
        errors = _update_project(ini_pdv, remote_names=remote_urls)
        cae.chk(15, not bool(errors), f"update errors in {project_path=}:{ppp(errors)}")

    _renew_prj_dir(ini_pdv)
    _refresh_pdv(ini_pdv, remote_urls=remote_urls)

    inc_part = cast(int, get_app_option(ini_pdv, 'versionIncrementPart'))
    project_version = latest_remote_version(ini_pdv, increment_part=inc_part)
    errors = replace_file_version(ini_pdv['version_file'], version=project_version, increment_part=0)
    cae.chk(15, not bool(errors), errors)
    # refresh ini_pdv (project_version and related project dev variables like project_title)
    _refresh_pdv(ini_pdv, remote_urls=remote_urls)

    errors = update_frozen_req_files(ini_pdv)  # check|update **/*requirements_frozen.txt files
    cae.chk(15, not bool(errors), f"frozen requirements files update errors:{ppp(errors)}")

    with in_prj_dir_venv(project_path):
        man = check_templates(cae, ini_pdv)
        if not man:
            return ini_pdv
        man.deploy()

    dst_files = set(dst_path for dst_path, mf in man.deploy_files.items() if not mf.up_to_date)
    dbg_msg = (": " + " ".join(os_path_relpath(_, project_path) for _ in dst_files)) if debug_or_verbose() else ""
    cae.po(f" ---- renewed {len(dst_files)} managed files{dbg_msg}")

    git_init_add(ini_pdv)
    git_renew_remotes(project_path, git_push_url(ini_pdv, remote_urls=remote_urls), upstream_url=ini_pdv['repo_url'],
                      origin_name=ini_pdv['REMOTE_ORIGIN'], upstream_name=ini_pdv['REMOTE_UPSTREAM'],
                      remotes=remote_urls)
    _refresh_pdv(ini_pdv)       # refresh 'remote_urls' from updated git remote urls

    if ini_pdv['namespace_name'] and project_type != ROOT_PRJ:     # is namespace portion
        _renew_local_root_req_file(ini_pdv)

    cae.po(f" ==== successfully {action} {ini_pdv['project_title']}")

    return ini_pdv


def _renew_local_root_req_file(pdv: ProjectDevVars):
    namespace_name = pdv['namespace_name']
    project_name = pdv['project_name']
    req_dev_file_name = pdv['REQ_DEV_FILE_NAME']
    root_imp_name = namespace_name + '.' + namespace_name
    root_pkg_name = norm_name(root_imp_name)

    root_prj_path = os_path_join(os_path_dirname(pdv['project_path']), root_pkg_name)
    if not os_path_isdir(root_prj_path):
        cae.po(f"  ### {namespace_name} namespace root project not found locally in {root_prj_path}")
        cae.po(f"  ### ensure to manually add {project_name} to {req_dev_file_name} of {namespace_name} namespace root")
        return

    root_req = os_path_join(root_prj_path, req_dev_file_name)
    if os_path_isfile(root_req):
        req_content = read_file(root_req)
    else:
        cae.dpo(f"    # {root_req} not found in {root_imp_name} namespace root project path: creating ...")
        req_content = ""

    sep = os.linesep
    if not _required_package(project_name, req_content.split(sep)):
        if req_content and not req_content.endswith(sep):
            req_content += sep
        write_file(root_req, req_content + project_name + sep)


def _required_package(import_or_package_name: str, packages_versions: list[str]) -> bool:
    project_name, _ = project_name_version(import_or_package_name, packages_versions)
    return bool(project_name)


def _show_remote_gitlab(prj_instance: Project, branch: str = "") -> bool:
    if not prj_instance:
        return False

    verbose = debug_or_verbose()

    for attr in sorted(prj_instance.attributes) if verbose else ('created_at', 'default_branch', 'visibility'):
        cae.po(f"    - {attr} = {getattr(prj_instance, attr, None)}")

    if branch:
        mrs = prj_instance.mergerequests.list(source_branch=branch, state='opened', get_all=False)
        if mrs:
            cae.po(f"✅   - an open Merge Request (with the ID {mrs[0].iid}) already exists for {branch=} at remote")
        elif verbose:
            cae.po(f"    - no open Merge Request found for the {branch=} found at remote")

    cae.po(f"    - protected branches = {PPF(prj_instance.protectedbranches.list())}")
    try:                                                # raises 403 Forbidden if not owner/maintainer
        cae.po(f"   -- protected tags = {PPF(prj_instance.protectedtags.list())}")
    except (GitlabListError, Exception) as ex:          # pylint: disable=broad-exception-caught
        if debug_or_verbose():
            cae.po(f"    # determining protected tag raises {ex=}")

    return True


# pylint: disable-next=too-many-locals,too-many-branches,too-many-statements
def _show_status(ini_pdv: ProjectDevVars) -> str:
    """ show git status and a guess of the next action for the specified/current project on the local machine. """
    verbose = debug_or_verbose()
    project_path = ini_pdv['project_path']
    project_type = ini_pdv['project_type']
    main_branch = ini_pdv['MAIN_BRANCH']
    cur_branch = git_current_branch(project_path)
    remote_urls = ini_pdv.pdv_val('remote_urls')

    if verbose:
        sh_kwargs = {'exit_on_err': False, 'app_obj': cae}

        cae.dpo("  --- setup.py check:")
        sh_exit_if_exec_err(14, "python setup.py check", **sh_kwargs)           # prints output if cae.debug

        cae.po("  --- editable packages:")
        output: list[str] = []
        sh_exit_if_exec_err(14, PIP_CMD, extra_args=("list", "--editable"), lines_output=output, **sh_kwargs)
        for line in [] if cae.debug else output:                                # sh_exit*() prints output if cae.debug
            cae.po(f"      {line}")

        cae.po("  --- outdated packages:")
        output = []
        sh_exit_if_exec_err(14, PIP_CMD, extra_args=("list", "--outdated"), lines_output=output, **sh_kwargs)
        for line in [] if cae.debug else output:
            cae.po(f"      {line}")

        cae.po("  --- project vars:")
        _print_pdv(ini_pdv)

    if verbose and project_type in (PARENT_PRJ, ROOT_PRJ):
        presets = _init_children_presets(ini_pdv, ini_pdv.pdv_val('children_project_vars'))
        cae.po(f"  --- {len(presets)} children presets: ")
        nsp_len = len(ini_pdv['namespace_name'])
        if nsp_len:
            nsp_len += 1
        for preset, dep_packages in presets.items():
            cae.po(f"      {preset: <9} == {', '.join(pkg[nsp_len:] for pkg in sorted(dep_packages))}")

    if project_type != PARENT_PRJ:
        extra_diff_args = () if verbose else ("--compact-summary", )  # alt: --name-only

        if cur_branch != main_branch:
            cae.po(f"   -- current working branch of project at '{project_path}' is '{cur_branch}'")
            output = git_diff(project_path, *extra_diff_args, main_branch)
            if output and (not output[0].startswith(EXEC_GIT_ERR_PREFIX) or verbose):
                cae.po(f"  --- git diff {cur_branch} against {main_branch} branch:{ppp(output)}")

        output = git_diff(project_path, *extra_diff_args)
        if output and (not output[0].startswith(EXEC_GIT_ERR_PREFIX) or verbose):
            cae.po(f"  --- git diff - to be staged/added:{ppp(output)}")

        remote_branch = f"{ini_pdv['REMOTE_ORIGIN']}/{main_branch}"
        output = git_diff(project_path, *extra_diff_args, main_branch, remote_branch)
        if output and (not output[0].startswith(EXEC_GIT_ERR_PREFIX) or verbose):
            cae.po(f"  --- git diff {main_branch} {remote_branch} ('pjm update' to update branch):{ppp(output)}")

        if verbose:
            cae.po(f"   -- git status:{ppp(git_status(project_path, verbose=verbose))}")
            cae.po(f"   -- branches:{ppp(git_branches(project_path))}")
            cae.po(f"   -- remotes:{ppp(f'{name}={url}' for name, url in remote_urls.items())}")

        changed = git_uncommitted(project_path)
        if changed:
            cae.po(f" ---- '{project_path}' has {len(changed)} uncommitted files: {changed}")

        if verbose:
            commits = git_any(project_path, 'rev-list', '@{u}..HEAD')
            if commits:
                cae.po(f"   -- ahead commits:{ppp(commits)}")
            commits = git_any(project_path, 'rev-list', 'HEAD..@{u}')
            if commits:
                cae.po(f"   -- behind commits:{ppp(commits)}")
        else:
            ahead_count = git_any(project_path, 'rev-list', '--count', '@{u}..HEAD')
            behind_count = git_any(project_path, 'rev-list', '--count', 'HEAD..@{u}')
            if not (ahead_count[0].startswith(EXEC_GIT_ERR_PREFIX) and behind_count[0].startswith(EXEC_GIT_ERR_PREFIX)):
                cae.po(f"   -- the current local branch is commits ahead={ahead_count[0]} behind={behind_count[0]}")

        local_version = ini_pdv['project_version']
        version_tag = ini_pdv['VERSION_TAG_PREFIX'] + local_version
        version_remotes = git_tag_remotes(project_path, version_tag, remote_names=remote_urls)
        if version_remotes:
            cae.po(f"   -- remotes having local version tag {version_tag}={version_remotes}")
        release_branch = ini_pdv['RELEASE_REF_PREFIX'] + local_version
        release_remotes = git_tag_remotes(project_path, release_branch, remote_names=remote_urls)
        if release_remotes:
            cae.po(f"   -- remotes having release tag {release_branch}={release_remotes}")
        if cur_branch != main_branch:
            branch_remotes = git_branch_remotes(project_path, cur_branch, remote_names=remote_urls)
            if branch_remotes:
                cae.po(f"   -- remotes having current branch: {branch_remotes}")

        next_action = guess_next_action(ini_pdv)
        if next_action.startswith("¡"):
            cae.po(f"  *** next action discrepancy: {next_action[1:]}")
        else:
            cae.po(f"   -- next action guess: {next_action}")

    return f" ==== displayed project status of {ini_pdv['project_title']}"


# pylint: disable-next=too-many-locals,too-many-branches
def _update_project(ini_pdv: ProjectDevVars, remote_names: Container[str] = (), hard_reset: bool = False) -> list[str]:
    """ update projects main branch from remotes, returning an empty string or a text block with error messages.

    :param ini_pdv:             project dev vars.
    :param remote_names:        names of the existing remotes.
    :param hard_reset:          pass True to reset the local repository, while deleting all local changes.
    :return:                    list of errors. some errors get ignored and not returned.
    """
    verbose = debug_or_verbose()
    remote_names = remote_names or ini_pdv.pdv_val('remote_urls')
    if not remote_names:
        if verbose:
            cae.po("    # skipped _update_project() because of missing remotes")
        return []

    project_path = ini_pdv['project_path']
    main_branch = ini_pdv['MAIN_BRANCH']
    origin_name = ini_pdv['REMOTE_ORIGIN']
    origin_branch = f"{origin_name}/{main_branch}"
    upstream_name = ini_pdv['REMOTE_UPSTREAM']
    forked = upstream_name in remote_names
    current_branch = git_current_branch(project_path)

    output = git_fetch(project_path, "--tags", origin_name)
    if output and output[0].startswith(EXEC_GIT_ERR_PREFIX):
        if verbose:
            cae.po(f"   ## ignoring fetch error from unavailable/missing {origin_name}:{ppp(output)}")
        return []
    if verbose:
        cae.po(f"   -- successfully fetched/updated the local project {ini_pdv['project_title']} from {origin_name}")
    if forked:
        output = git_fetch(project_path, upstream_name)
        if output and output[0].startswith(EXEC_GIT_ERR_PREFIX):
            cae.po(f"   ## ignoring error ({output}) in --tags fetch from {upstream_name}")
        elif verbose:
            cae.po(f"   -- successfully fetched the local project {ini_pdv['project_title']} from {upstream_name}")

    output = git_any(project_path, "branch", "--quiet", "--set-upstream-to", origin_branch, main_branch)
    if verbose and output and output[0].startswith(EXEC_GIT_ERR_PREFIX):
        cae.po(f"   ## ignoring error ({output}) in setting upstream branch tracking of '{origin_branch}'")

    errors = []

    if err_msg := git_checkout(project_path, main_branch):
        errors += [f"_update_project checkout {main_branch=} {err_msg=}"]

    remote_branch = f"{upstream_name}/{main_branch}" if forked else origin_branch
    if hard_reset:  # delete all local changes by using git reset --hard <remote-branch> instead of merge
        output = git_any(project_path, "reset", "--hard", remote_branch)
        if verbose and output and output[0].startswith(EXEC_GIT_ERR_PREFIX):
            cae.po(f"   ## ignoring error ({output}) in resetting local {main_branch=} from '{remote_branch=}'")
    else:
        output = git_merge(project_path, remote_branch, "--ff-only", commit_msg_text="pjm update_project ff-only merge")
        if verbose and output and output[0].startswith(EXEC_GIT_ERR_PREFIX):
            cae.po(f"   ## ignoring error ({output}) in fast-forward merge from {remote_branch=}")

    if forked:
        opt = ["--force"] if hard_reset else []
        output = git_push(project_path, git_push_url(ini_pdv, authenticate=True), main_branch, *opt, exit_on_err=False)
        if verbose and output and output[0].startswith(EXEC_GIT_ERR_PREFIX):
            cae.po(f"   ## ignoring error ({output}) in updating {main_branch} from {upstream_name} onto {origin_name}")

    if err_msg := git_checkout(project_path, current_branch):
        errors += [f"_update_project failed to restore the previously checked-out {current_branch=} {err_msg=}"]

    return errors


def _wait(pdv: ProjectDevVars):
    wait_seconds = float(cast(Union[str, int, float], get_app_option(pdv, 'delay')))
    cae.po(f"    . waiting {wait_seconds} seconds")
    time.sleep(wait_seconds)


# --------------- git remote repo connection --------------------------------------------------------------------------

class RemoteHost:
    """ base class registering subclasses as remote repo or web host class in :data:`REGISTERED_HOSTS_CLASS_NAMES`. """
    var_prefix: str = 'repo_'       # default config variable name prefix

    create_branch: Callable
    release_project: Callable
    repo_obj: Callable
    request_merge: Callable

    def __init_subclass__(cls, **kwargs):
        """ register a remote host class name; called on declaration of a subclass of :class:`RemoteHost`. """
        # global REGISTERED_HOSTS_CLASS_NAMES
        REGISTERED_HOSTS_CLASS_NAMES[camel_to_snake(cls.__name__)[1:].replace('_', '.').lower()] = cls.__name__
        super().__init_subclass__(**kwargs)

    def repo_merge_src_dst_fork_branch(self, ini_pdv: ProjectDevVars) -> tuple[RepoType, RepoType, bool, str]:
        """ determine instances of remote source and destination repositories, if it is forked and the branch to merge.

        :param ini_pdv:         project dev vars.
        :return:                tuple of source project, destination project, forked-state and the branch name.
        """
        branch = get_branch(ini_pdv)
        domain = get_host_domain(ini_pdv)
        group_name = get_host_group(ini_pdv, domain)
        project_name = ini_pdv['project_name']
        remote_urls = ini_pdv.pdv_val('remote_urls')

        upstream_name = ini_pdv['REMOTE_UPSTREAM']
        forked = upstream_name in remote_urls
        if forked:
            owner_name = remote_urls[upstream_name].split('/')[-2]
            cae.chk(64, owner_name == group_name, f"upstream/owner-group mismatch: '{owner_name}' != '{group_name}'")
            user_name = get_host_user_name(ini_pdv, domain)
        else:
            user_name = group_name

        origin_name = ini_pdv['REMOTE_ORIGIN']
        origin_user = remote_urls.get(origin_name, "/").split('/')[-2]
        cae.chk(64, origin_user == user_name, f"{origin_name}/user mismatch: '{origin_user}' != '{user_name}'")

        # target_project_id/project_id is the upstream/forked and source_project_id is the origin/fork
        src = self.repo_obj(65, f"{user_name}/{project_name}")
        tgt = self.repo_obj(66, f"{group_name}/{project_name}")

        return src, tgt, forked, branch

    def repo_release_project(self, ini_pdv: ProjectDevVars, version_tag: str) -> str:
        """ prepare project release and reset local repository, optionally create release branch and publish to PyPI.

        :param ini_pdv:         project dev vars.
        :param version_tag:     version tag of the project release.
        :return:                end-of-action confirmation message, to be printed to console.
        """
        project_path = ini_pdv['project_path']
        main_branch = ini_pdv['MAIN_BRANCH']
        remote_branch = f"{ini_pdv['REMOTE_ORIGIN']}/{main_branch}"
        remote_names = ini_pdv.pdv_val('remote_urls')

        errors = _update_project(ini_pdv, remote_names=remote_names)
        cae.chk(84, not bool(errors), f"update project errors:{ppp(errors)}" + hint(
            'pjm', self.release_project, " later to retry if server is currently unavailable, or check remotes config"))

        # switch back to local main_branch and then merge-in the release-branch&-tag from remotes/origin/main_branch
        git_checkout(project_path, "-B", main_branch, force=bool(get_app_option(ini_pdv, 'force')),
                     remote_names=remote_names)
        git_merge(project_path, remote_branch, commit_msg_file=ini_pdv['COMMIT_MSG_FILE_NAME'])

        if version_tag == 'LATEST':
            pkg_version = latest_remote_version(ini_pdv, increment_part=0)
            version_tag = ini_pdv['VERSION_TAG_PREFIX'] + pkg_version
        else:
            pkg_version = _check_version(version_tag, prefix_to_check=ini_pdv['VERSION_TAG_PREFIX'])

        tag_remotes = set(git_tag_remotes(project_path, version_tag, remote_names=remote_names))
        cae.chk(85, set(remote_names) == tag_remotes, f"missing {version_tag=} at {set(remote_names) - tag_remotes}")

        msg = f"updated local {main_branch} branch"
        if ini_pdv['pip_name']:  # create release*ver branch only for projects available in PyPi via pip
            release_branch = ini_pdv['RELEASE_REF_PREFIX'] + pkg_version
            cae.chk(85, not git_ref_in_branch(project_path, release_branch, branch=remote_branch),
                    f"release branch {release_branch} already exists in the {remote_branch=}")
            cae.dpo(f"   -- creating branch '{release_branch}' for tag '{version_tag}' at {remote_branch=}")
            prj_id = f"{get_host_group(ini_pdv, get_host_domain(ini_pdv))}/{ini_pdv['project_name']}"
            self.create_branch(prj_id, release_branch, version_tag)
            msg += f" and released {pkg_version} onto new protected release branch {release_branch}"

        return f" ==== {msg} of {ini_pdv['project_title']}"


class GithubCom(RemoteHost):
    """ remote connection and actions on remote repo in gitHub.com. """
    connection: Optional[Github] = None     #: connection to GitHub host

    def connect(self, ini_pdv: ProjectDevVars) -> bool:
        """ connect to gitHub.com remote host.

        :param ini_pdv:         project dev vars (only using the value of the 'repo_token' variable).
        :return:                boolean True on successful authentication else False.
        """
        try:
            self.connection = Github(auth=Auth.Token(ini_pdv['repo_token']))
        except (Exception, ) as ex:                                 # pylint: disable=broad-exception-caught
            cae.po(f"****  Github authentication exception: {mask_token(str(ex))}")
            self.connection = None
            return False
        return True

    def create_branch(self, group_repo: str, branch_name: str, tag_name: str):
        """ create a new remote branch onto/from the tag name.

        :param group_repo:      string with owner-user-name/repo-name of the repository, e.g. "UserName/RepositoryName".
        :param branch_name:     name of the branch to create.
        :param tag_name:        name of the tag/ref to create the branch from.
        """
        prj = self.repo_obj(86, "create branch error", group_repo)
        if prj is None:
            cae.po(f" **** group/repository {group_repo} not available; not created {branch_name=} for {tag_name=}")
            return

        try:
            git_tag = prj.get_git_tag(tag_name)     # https://gist.github.com/ursulacj/36ade01fa6bd5011ea31f3f6b572834e
            prj.create_git_ref(f'refs/heads/{branch_name}', git_tag.sha)
        except (GithubException, Exception):        # pylint: disable=broad-exception-caught
            cae.shutdown(86, error_message=f"error creating {branch_name=} for tag '{tag_name}': {format_exc()}")

        # protect the branch until GitHub Api supports wildcards in the initial push (see self.init_new_repo())
        self._protect_branches(prj, [branch_name])

    def group_obj(self, user_or_org_name: str) -> Optional[Union[AuthenticatedUser, Organization]]:
        """ instantiate am authenticated-user or organization object from the specified name.

        :param user_or_org_name:name of a user or organization.
        :return:                instantiated user/organization object or None if name not found as user/org.
        """
        if not self.connection:
            return None

        auth_user = self.connection.get_user()  # get_user(user_or_org)->NamedUser-obj, not having create_repo() method
        if user_or_org_name.lower() == auth_user.login.lower():
            return cast(AuthenticatedUser, auth_user)

        try:
            return self.connection.get_organization(user_or_org_name)
        except UnknownObjectException:
            return None

    def init_new_repo(self, group_repo: str, project_desc: str, main_branch: str):
        """ config new project repo.

        :param group_repo:      project owner user and repository names in the format "user-name/repo-name".
        :param project_desc:    project description.
        :param main_branch:     name of the default/main branch.
        """
        project_repo = self.repo_obj(78, "repository initialization error", group_repo)
        if project_repo is None:
            cae.po(f" **** group/repository {group_repo} not available; skipped properties/protected-branch setup")
            return

        cae.vpo(f"    - setting remote project properties of new repository '{group_repo}'")
        project_repo.edit(default_branch=main_branch, description=project_desc, visibility='public')

        branch_masks = [main_branch]      # , f'{ini_pdv['RELEASE_REF_PREFIX']}*']
        self._protect_branches(project_repo, branch_masks)
        # the GitHub REST api does still not allow creating branch protection with a wildcard (for release*)
        # .. see https://github.com/orgs/community/discussions/24703
        # current workaround is to protect individual release branch in the release_project action

        cae.po(f"   == initialized project and created {len(branch_masks)} protected branch(es): {branch_masks}")

    def repo_obj(self, err_code: int, err_msg: str, group_repo: str) -> Optional[Repository]:
        """ convert user repo names to a repository instance of the remote api.

        :param err_code:        error code, pass 0 to not quit if a project is not found.
        :param err_msg:         error message to display on error. will be extended with
                                the group and project names from the :paramref:`~repo_obj.group_repo` argument.
        :param group_repo:      string with owner-user-name/repo-name of the repository, e.g. "UserName/RepositoryName".
        :return:                GitHub repository if found, else return None if err_code is zero else quit.
        """
        try:
            assert self.connection  # mypy
            # search for repo projects: repos = list(self.connection.search_repositories(query="user:AndiEcker"))
            return self.connection.get_repo(group_repo)
        except (GithubException, Exception) as gh_ex:           # pylint: disable=broad-exception-caught
            if err_code:
                cae.shutdown(err_code, error_message=err_msg.format(name=group_repo))
            elif debug_or_verbose():
                cae.po(f"   * repository '{group_repo}' not found on connected remote server (exception: {gh_ex})")
            return None

    @staticmethod
    def _protect_branches(project_repo: Repository, branch_masks: list[str]):
        for branch_mask in branch_masks:
            # see also GitHub WebUI docs: https://docs.github.com/de/rest/branches/branch-protection and
            # https://docs.github.com/de/repositories/configuring-branches-and-merges-in-your-repository/...
            # ...managing-protected-branches/managing-a-branch-protection-rule
            # example: https://github.com/txqueuelen/reposettings/blob/master/reposettings.py
            # .. done with powerscript: https://medium.com/objectsharp/...
            # ...adding-branch-protection-to-your-repo-with-the-github-rest-api-and-powershell-67ee19425e40
            branch_obj = project_repo.get_branch(branch_mask)
            cae.vpo(f"    - protecting branch {branch_mask}")
            branch_obj.edit_protection(strict=True)

    # ----------- remote action methods ----------------------------------------------------------------------------

    @_action(PARENT_PRJ, *ANY_PRJ_TYPE, arg_names=(('group|user-slash-repo-to-fork-from', ), ), shortcut='fork')
    def fork_project(self, ini_pdv: ProjectDevVars, fork_repo_path: str):
        """ create/renew a fork of a remote repo specified via the 1st argument, into our user namespace. """
        domain = get_host_domain(ini_pdv)
        cae.chk(20, domain == 'github.com', f"invalid host domain '{domain}'! add option --repo_domain=github.com")

        prj = self.repo_obj(20, "user account/repository fork error", fork_repo_path)
        if prj is None or not self.connection:
            cae.po(f" **** user account/repository {fork_repo_path} not available")
        else:
            cast(AuthenticatedUser, self.connection.get_user()).create_fork(prj)
            cae.po(f" ==== forked {ini_pdv['project_title']} on {domain}")

    @_action(*ANY_PRJ_TYPE, shortcut='push')
    def push_project(self, ini_pdv: ProjectDevVars):
        """ push the current/specified branch of project/package version-tagged to the remote repository host.

        :param ini_pdv:             project dev vars.
        """
        _check_action(ini_pdv, self.push_project)

        project_path = ini_pdv['project_path']
        project_name = ini_pdv['project_name']
        owner_project = owner_project_from_url(ini_pdv.pdv_val('remote_urls')[ini_pdv['REMOTE_ORIGIN']])

        changed = git_uncommitted(project_path)
        cae.chk(16, not changed, f"{project_name} has {len(changed)} uncommitted files: {changed}")

        new_repo = False
        push_refs = []
        if not self.repo_obj(0, "", owner_project) and self.connection:
            usr_obj = cast(AuthenticatedUser, self.connection.get_user())
            usr_obj.create_repo(project_name)   # if not, then git push throws the error "Repository not found"
            new_repo = True
            push_refs.append(ini_pdv['MAIN_BRANCH'])

        branch_name = get_branch(ini_pdv)
        if branch_name and branch_name not in push_refs:
            push_refs.append(branch_name)

        push_refs.append(_check_and_add_version_tag(ini_pdv))

        output = git_push(project_path, git_push_url(ini_pdv, authenticate=True), "--set-upstream", *push_refs)
        if debug_or_verbose():
            cae.po(ppp(output))

        if new_repo:    # branch protection rules have to be created after branch creation done by git push
            self.init_new_repo(owner_project, ini_pdv['project_title'], ini_pdv['MAIN_BRANCH'])

        cae.po(f" ==== pushed {' '.join(push_refs)} branches/tags to remote project {owner_project}")

    @_action(*ANY_PRJ_TYPE, arg_names=(("version-tag", ), ('LATEST', )), shortcut='release')
    def release_project(self, ini_pdv: ProjectDevVars, version_tag: str):
        """ update local main branch from origin, and if pip_name is set, then release the latest/specified version too.

        :param ini_pdv:         project dev vars.
        :param version_tag:     push version tag in the format ``v<version-number>`` to release or ``LATEST`` to use
                                the version tag of the latest git repository version.
        """
        _check_action(ini_pdv, self.release_project)

        cae.po(self.repo_release_project(ini_pdv, version_tag))

    @_action(*ANY_PRJ_TYPE, shortcut='request')
    def request_merge(self, ini_pdv: ProjectDevVars):
        """ request merge of the origin=fork repository into the main branch at remote/upstream=forked. """
        # see https://docs.github.com/de/rest/pulls/pulls?apiVersion=2022-11-28#create-a-pull-request
        _check_action(ini_pdv, self.request_merge)

        src_prj, tgt_prj, forked, branch = self.repo_merge_src_dst_fork_branch(ini_pdv)
        if TYPE_CHECKING:
            assert isinstance(src_prj, Repository)
            assert isinstance(tgt_prj, Repository)

        project_path = ini_pdv['project_path']
        main_branch = ini_pdv['MAIN_BRANCH']
        commit_msg_file = check_commit_msg_file(project_path, 'pjm', prepare_commit, " to create a commit message file",
                                                commit_msg_file=ini_pdv['COMMIT_MSG_FILE_NAME'])
        commit_msg_title, commit_msg_body = read_file(commit_msg_file).split(os.linesep, maxsplit=1)
        merge_req = tgt_prj.create_pull(base=main_branch, head=branch, title=commit_msg_title, body=commit_msg_body)
        if debug_or_verbose():
            diff_url = merge_req.diff_url
            cae.po(f"    . merge request diffs available at: {diff_url}")

        action = "requested merge"
        if not forked:
            _wait(ini_pdv)  # wait for the created un-forked/direct maintainer merge request
            tgt_prj.merge(base=main_branch, head=branch, commit_message=commit_msg_title + os.linesep + commit_msg_body)
            action = "auto-merged un-forked merge request"

        cae.po(f" ==== {action} of branch {branch} from fork/origin ({src_prj.id}) into upstream ({tgt_prj.id})")

    @_action(PARENT_PRJ, *ANY_PRJ_TYPE, shortcut='status')
    def show_status(self, ini_pdv: ProjectDevVars):
        """ show git status of the specified/current project locally and on remote. """
        end_msg = _show_status(ini_pdv)

        domain = get_host_domain(ini_pdv)
        cae.chk(19, domain == 'github.com', f"invalid host domain '{domain}'! add option --repo_domain=github.com")
        group_name = get_host_group(ini_pdv, domain)
        prj_instance = self.repo_obj(0, "repository status fetch error", f"{group_name}/{ini_pdv['project_name']}")
        if prj_instance is not None:   # project got already pushed to remote
            cae.vpo("✅   # remote status for GitHub not implemented")

        cae.po("=" + end_msg[1:])


class GitlabCom(RemoteHost):
    """ remote connection and actions on gitlab.com. """
    connection: Optional[Gitlab] = None     #: connection to Gitlab host

    def branch_merge_requests(self, ini_pdv: ProjectDevVars, branch: str) -> list[ProjectMergeRequest]:
        """ determine the merge/pull requests (opened or closed) for the specified branch.

        :param ini_pdv:         project dev vars.
        :param branch:          name of the branch to determine the merge/pull requests.
        :return:                found merge/pull requests for the specified branch or empty list on error.
        """
        group_repo = f"{get_host_group(ini_pdv, get_host_domain(ini_pdv))}/{ini_pdv['project_name']}"
        project = self.repo_obj(95, group_repo)
        return [] if project is None else project.mergerequests.list(source_branch=branch)

    def connect(self, ini_pdv: ProjectDevVars) -> bool:
        """ connect to gitlab.com remote host.

        :param ini_pdv:         project dev vars (REPO_HOST_PROTOCOL, host_domain, host_token).
        :return:                boolean True on successful authentication else False.
        """
        token = ini_pdv['repo_token']
        try:
            self.connection = Gitlab(ini_pdv['REPO_HOST_PROTOCOL'] + ini_pdv['repo_domain'], private_token=token)
            if cae.debug:
                self.connection.enable_debug()
            self.connection.auth()          # authenticate and create user attribute
        except (Exception, ) as ex:         # pylint: disable=broad-exception-caught
            cae.po(f"****  Gitlab connect exception: {mask_token(str(ex))}" + ("" if token else " (empty repo_token)"))
            self.connection = None
            return False
        return True

    def create_branch(self, owner_prj: str, branch_name: str, tag_name: str):
        """ create a new remote branch onto/from the tag name.

        :param owner_prj:       owner-user-name and name of the repository, e.g. "OwnerName/RepositoryName".
        :param branch_name:     name of the branch to create.
        :param tag_name:        name of the tag/ref to create the branch from.
        """
        cae.dpo(f"   -- creating branch '{branch_name}' for tag '{tag_name}' at the remote")
        prj = self.repo_obj(86, owner_prj)
        if prj is None:  # never None because shutdown() call, but added if to make mypy happy
            return
        try:
            prj.branches.create({'branch': branch_name, 'ref': tag_name})
        except (GitlabHttpError, GitlabCreateError, GitlabError, Exception):    # pylint: disable=broad-exception-caught
            cae.shutdown(86, error_message=f"error '{format_exc()}' creating {branch_name=} for tag '{tag_name}'")

    def init_new_remote_repo(self, ini_pdv: ProjectDevVars) -> str:
        """ create a group/user project specified in ini_pdv or quit with error if group/user not found.

        :param ini_pdv:         project dev vars.
        :return:                error message or empty string if no errors occurred.
        """
        owner_obj = self.project_owner(ini_pdv)
        project_name = ini_pdv['project_name']
        main_branch = ini_pdv['MAIN_BRANCH']
        project_properties = {
            'name': project_name,
            'description': ini_pdv['project_desc'],
            'default_branch': main_branch,
            'visibility': 'public',
        }
        if isinstance(owner_obj, User):
            project_properties['user_id'] = owner_obj.id
        else:
            project_properties['namespace_id'] = owner_obj.id
        cae.vpo(f"    - remote project properties of new package {project_name}: {PPF(project_properties)}")

        retries = 3
        while retries and self.connection:
            try:
                # using UserProtectManager|owner_obj.projects.create() for user projects results in 403 Forbidden error
                project = self.connection.projects.create(project_properties)
                cae.po(f"   == created new remote project repository for user/group '{owner_obj.name}'")
                if debug_or_verbose():
                    cae.po(f"    = remote project attributes={PPF(project.attributes)}")

                _wait(ini_pdv)

                for branch_mask in (main_branch, ini_pdv['RELEASE_REF_PREFIX'] + '*'):
                    protected_branch_properties = {'name': branch_mask,
                                                   'merge_access_level': MAINTAINER_ACCESS,
                                                   'push_access_level': MAINTAINER_ACCESS}
                    cae.vpo(f"    - {branch_mask} protected branch properties: {protected_branch_properties}")
                    project.protectedbranches.create(protected_branch_properties)
                cae.po(f"   == created 2 protected branches: '{main_branch}' and '{ini_pdv['RELEASE_REF_PREFIX']}*'")
                return ""

            except (GitlabHttpError, GitlabCreateError, Exception) as ex:   # pylint: disable=broad-exception-caught
                # 400: {'namespace': ['is not valid']} get raised also on insufficient access rights/role
                cae.po(f"   ** exception {ex=} raised in init_new_repo(); {retries=} props={PPF(project_properties)}")
                _wait(ini_pdv)
                retries -= 1

        return f"  *** failed to create new remote project {project_name} with {project_properties=}"

    # pylint: disable-next=too-many-locals
    def merge_pushed_project(self, pdv: ProjectDevVars,
                             request: Optional[ProjectMergeRequest] = None, message: str = "", max_wait: float = 6.9
                             ) -> int:
        """ merge an MR of the specified project.

        :param pdv:             project dev vars.
        :param request:         pass MergeRequest instance for direct merge of unforked repository.
        :param message:         commit message file content. will be read from project root folder if empty|not-passed.
        :param max_wait:        maximum waiting time in seconds for all the retries of the merge. the delay between
                                each retry can be specified via the --delay option.
        :return:                number of retries left. returns zero if merge did fail (consuming all retries).
        """
        project_path = pdv['project_path']
        forked = request is None
        delay = pdv.pdv_val('main_app_options').get('delay', 6.9)
        retries = int(max_wait / delay) + 1

        if forked:  # request is None
            requests = self.branch_merge_requests(pdv, branch := git_current_branch(project_path))
            if not requests:
                cae.shutdown(88, error_message=f"no merge request found for {project_path=} and {branch=}")
            cae.chk(88, len(requests) == 1, f"multiple merge {requests=} found for {project_path=} and {branch=}")
            request = requests[0]
        if request is None or self.connection is None:  # mypy doesn't see: self.shutdown() terminates app
            return 0

        if not message:
            message = read_file(os_path_join(project_path, pdv['COMMIT_MSG_FILE_NAME']))

        while retries:
            _wait(pdv)
            try:                                        # ignore timeout or if not a maintainer: 405-Method Not Allowed
                mr_merge_attributes = request.merge(merge_commit_message=message)
                sh_log(f"gitlab-python.{request=}.merge() -> {mr_merge_attributes=} {retries=}", log_name_prefix='git')
                break
            except (GitlabError, Exception) as ex:      # pylint: disable=broad-exception-caught
                cae.po(f"    # auto-merge exception {ex=} - permission error or --{delay=} too short: left {retries=}")
                retries -= 1

        if errors := _update_project(pdv):  # update remote branches and tags now merged also into origin/main_branch
            cae.po(f"    * ignored post merge update errors: {ppp(errors)}")

        if forked and retries:  # for forked repos create version tag; they don't get it (like origin) per git push
            version_tag = pdv['VERSION_TAG_PREFIX'] + pdv['project_version']
            try:
                project = self.connection.projects.get(request.project_id)
                project.tags.create({'tag_name': version_tag, 'ref': request.sha})
                cae.po(f"    - created {version_tag=} for {project=} and the branch ref {request.sha=}")
            except (GitlabError, Exception) as ex:      # pylint: disable=broad-exception-caught
                cae.po(f"   ** create {request.project_id=}/{getattr(request, 'sha', '')} {version_tag=} raised {ex=}")
                retries = 0

        return retries

    def repo_obj(self, err_code: int, owner_project: str) -> Optional[Project]:
        """ create Project instance of a remote repository specified by its namespace path or its endswith-fragment.

        :param err_code:        error code, pass 0 to not quit if the project is not found.
        :param owner_project:   identifies the remote repository by its owner (group|user) and its project name,
                                separated by a slash.
        :return:                python-gitlab project instance if found, else return None if err_code is zero else quit.
        """
        try:                                        # e.g., GitlabGetError: 404: 404 Project Not Found
            assert self.connection                  # mypy
            return self.connection.projects.get(owner_project)
        except (GitlabError, Exception) as ex:      # pylint: disable=broad-exception-caught
            msg = f"owner/project {owner_project} not found on remote {self.connection}; exception={ex})"
            if err_code:
                cae.shutdown(err_code, error_message=msg)
            elif debug_or_verbose():
                cae.po(f"   # {msg}")
            return None

    def project_owner(self, ini_pdv: ProjectDevVars) -> Union[Group, User]:
        """ get the owner (group|user) of the project specified by ini_pdv or quit with error if group/user not found.

        :param ini_pdv:         project dev vars.
        :return:                instance of Group or User, determined via the user-/group-names specified by ini_pdv.
        """
        domain = get_host_domain(ini_pdv)
        group_name = get_host_group(ini_pdv, domain)
        user_name = get_host_user_name(ini_pdv, domain)

        owner_obj: Optional[Union[Group, User]] = None

        if self.connection:
            try:
                owner_obj = self.connection.groups.get(group_name)
            except (GitlabError, Exception):                            # pylint: disable=broad-exception-caught
                try:
                    groups = self.connection.groups.list(search=group_name)
                    if groups:
                        owner_obj = groups[0]
                except (GitlabError, Exception):                        # pylint: disable=broad-exception-caught
                    pass    # owner_obj == None

            if owner_obj is None:
                try:
                    owner_obj = self.connection.users.get(user_name)
                except (GitlabError, Exception):                        # pylint: disable=broad-exception-caught
                    try:
                        users = self.connection.users.list(username=user_name)
                        if users:
                            owner_obj = users[0]
                    except (GitlabError, Exception):                    # pylint: disable=broad-exception-caught
                        pass    # owner_obj == None

        if owner_obj is None:
            cae.shutdown(37, error_message=f"neither {group_name=} nor {user_name=} found on repo host {domain=}")
            raise  # never executed; needed by mypy for owner_obj type checking # pylint: disable=misplaced-bare-raise

        return owner_obj

    # ----------- remote action methods ----------------------------------------------------------------------------

    @_action(*ANY_PRJ_TYPE)
    def clean_releases(self, ini_pdv: ProjectDevVars) -> list[str]:     # pylint: disable=too-many-locals
        """ delete local+remote release tags and branches of the specified project that got not published to PYPI. """
        pip_name = ini_pdv['pip_name']
        if not pip_name:
            cae.po(" ==== this project has no PyPi release tags/branches to clean")
            return []

        project_path = ini_pdv['project_path']

        all_branches = git_branches(project_path)
        cae.po(f"    - found {len(all_branches)} branches to check for to be deleted: {all_branches}")

        pypi_test = ini_pdv['parent_folder'] == 'TsT'
        pypi_releases = get_pypi_versions(pip_name, pypi_test=pypi_test)
        cae.chk(34, bool(pypi_releases), f"no {'TsT' if pypi_test else ''}PyPI releases found (check pip installation)")
        cae.po(f"    - found {len(pypi_releases)} PyPI release versions protected from to be deleted: {pypi_releases}")

        deleted = []
        for branch_name in all_branches:
            chk, *ver = branch_name.split('release')
            if len(ver) != 1 or ver[0] in pypi_releases:
                continue
            version = ver[0]
            if chk == f"remotes/{ini_pdv['REMOTE_ORIGIN']}/":   # un-deployed remote release branch found
                # protected release branch (ini_pdv['RELEASE_REF_PREFIX'] + '*') raises error on git push command:
                # git_push(project_path, _git_repo_url(ini_pdv, authentic=True), branch_name, extra_args=("--delete",))
                group_repo = f"{get_host_group(ini_pdv, get_host_domain(ini_pdv))}/{ini_pdv['project_name']}"
                project = self.repo_obj(33, group_repo)
                if project is None:  # never None because app.shutdown() call, but added if to make mypy happy
                    continue
                try:
                    project.protectedbranches.delete(branch_name)
                except GitlabError as ex:  # GitlabDeleteError on failed release upload
                    cae.po(f"    # try other method to delete protected branch {branch_name} on remote after err: {ex}")
                    try:
                        branch_obj = project.protectedbranches.get(branch_name)
                        branch_obj.delete()
                    except GitlabError as ex2:
                        cae.po(f"   ## ignoring error deleting release branch {branch_name} on origin remote: {ex2}")

                output = git_push(project_path, git_push_url(ini_pdv, authenticate=True),
                                  "--delete", ini_pdv['VERSION_TAG_PREFIX'] + version, exit_on_err=False)
                if output and output[0].startswith(EXEC_GIT_ERR_PREFIX):
                    cae.po(f"   ## deleting tag v{version} via push to remote failed with ignored error:{ppp(output)}")
                elif debug_or_verbose():
                    cae.po(f"    = git push output:{ppp(output)}")

                deleted.append(branch_name)

            elif not chk:                       # un-deployed local release branch found
                with in_prj_dir_venv(project_path):
                    sh_err = sh_exit_if_git_err(33, f"git branch --delete {branch_name}")
                    if sh_err:
                        cae.po(f"   ## ignoring error {sh_err} deleting branch {branch_name} via 'git branch --delete'")

                    sh_err = sh_exit_if_git_err(33, f"git tag --delete v{version}")
                    if sh_err:
                        cae.po(f"   ## ignoring error {sh_err} deleting local tag v{version} via 'git tag --delete'")

                deleted.append(branch_name)

        cae.po(f" ==== cleaned {len(deleted)} release branches and tags: {deleted}")

        return deleted

    @_action(PARENT_PRJ, *ANY_PRJ_TYPE, arg_names=(('group|user-slash-project-to-fork-from', ), ), shortcut='fork')
    # pylint: disable-next=too-many-locals,too-many-branches,too-many-statements
    def fork_project(self, ini_pdv: ProjectDevVars, owner_project_path: str):
        """ create or renew a fork of a remote repo, specified via the 1st argument, into our user namespace. """
        cae.chk(20, (slash_count := owner_project_path.count('/')) == 1,
                f"exact one slash (/) expected in the specified '{owner_project_path=}' (got {slash_count} slashes)")

        upstream_group, project_name = owner_project_path.split('/', maxsplit=1)

        if ini_pdv['project_type'] == PARENT_PRJ:
            project_path = os_path_join(ini_pdv['project_path'], project_name)
            os.makedirs(project_path, exist_ok=True)
            ini_pdv = _init_pdv(project_path=project_path)

        cae.chk(20, project_name == ini_pdv['project_name'],
                f"project name mismatch ('{project_name} != {ini_pdv['project_name']})!"
                f" change working directory to the project root folder or specify it with --project_path option..")

        domain = get_host_domain(ini_pdv)
        cae.chk(20, domain == 'gitlab.com', f"invalid host domain '{domain}'! add option --repo_domain=gitlab.com")

        user_name = get_host_user_name(ini_pdv, domain)
        conn = self.connection
        if debug_or_verbose() and conn and conn.user is not None and user_name != conn.user.name:
            cae.po(f"    # {domain} user name {conn.user.name=} differs from .env-configured-{user_name=}")

        host_url = f"{ini_pdv['REPO_HOST_PROTOCOL']}{domain}"
        user_url = f"{host_url}/{user_name}"  # clone at parent dir is creating the project root folder
        origin_url = f"{user_url}/{project_name}.git"  # after remotes renewed==_git_repo_url(ini_pdv, remotes=remotes)
        upstream_url = f"{host_url}/{upstream_group}/{project_name}.git"
        cae.chk(20, not bool(ups_failure := url_failure(upstream_url)),
                f"repository to fork from is not available at {upstream_url}; reason: {ups_failure}")

        project_path = ini_pdv['project_path']
        main_branch = ini_pdv['MAIN_BRANCH']
        origin_name = ini_pdv['REMOTE_ORIGIN']
        upstream_name = ini_pdv['REMOTE_UPSTREAM']
        remote_urls = ini_pdv.pdv_val('remote_urls')

        def _renew_forked():
            git_renew_remotes(project_path, origin_url, upstream_url=upstream_url,
                              origin_name=origin_name, upstream_name=upstream_name, remotes=remote_urls)

            git_fetch(project_path, upstream_name, exit_on_err=True)
            git_checkout(project_path, main_branch, remote_names=remote_urls)
            git_merge(project_path, f"{upstream_name}/{main_branch}",
                      commit_msg_text=f"pjm fork_project action merged the {main_branch} branch from {upstream_name}")
            latest_version_tag = git_tag_list(project_path, tag_pattern=ini_pdv['VERSION_TAG_PREFIX'] + "*")[-1]
            output = git_push(project_path, git_push_url(ini_pdv, authenticate=True), main_branch, latest_version_tag)
            if debug_or_verbose():
                cae.po(f"    = git push output:{ppp(output)}")
            cae.dpo(f"    - renewed the {project_name} repo at {origin_name} and {project_path} from {upstream_name}")

        ena_log = bool(get_app_option(ini_pdv, 'git_log'))
        if os_path_isdir(os_path_join(project_path, GIT_FOLDER_NAME)):  # renew if project path AND git repo exists
            ups_ok = remote_urls.get(upstream_name) == upstream_url
            ori_ok = remote_urls.get(origin_name) == origin_url
            cae.chk(20, ups_ok and ori_ok, "remote urls discrepancies for" +
                    ("" if ups_ok else f" upstream ({remote_urls.get(upstream_name)=} != {upstream_url=})") +
                    (" and" if not ups_ok and not ori_ok else "") +
                    ("" if ori_ok else f" origin ({remote_urls.get(origin_name)=} != {origin_url=})"))
            if ena_log:
                sh_log(f"# renewed fork_project {project_name=} enabled/extended git shell command logging",
                       log_file_paths=sh_logs(log_enable_dir=project_path, log_name_prefix='git'))
            _renew_forked()
            action = "renewed"
        else:
            remote_urls = {}
            action = 'created'

            prj_instance = self.repo_obj(20, owner_project_path)
            if prj_instance is not None:            # never None because shutdown() call (added if to make mypy happy)
                try:
                    prj_instance.forks.create({})   # not-needed/defaults-to {'namespace_path': user_name/project_name}
                except (GitlabAuthenticationError, GitlabCreateError, GitlabError) as ex:
                    if getattr(ex, 'response_code', 0) == 409:  # project namespace|Name|Path has already been taken
                        cae.po(f"    # {owner_project_path} got already forked in {user_name}/{project_name}")
                        action = "locally refreshed"
                    else:
                        cae.shutdown(20, error_message=f"new fork of {owner_project_path} to {user_name} raised {ex=}")

            wait_seconds = 36
            while (reason := url_failure(origin_url)) and wait_seconds > 0:
                cae.po(f" . . .waiting for repository fork at {origin_url=} (to be {action}, unavailable {reason=})")
                time.sleep(6)
                wait_seconds -= 6
            cae.chk(20, wait_seconds > 0, f"timeout in waiting for repository fork at {origin_url=}")

            prj_path = git_clone(user_url, project_name, parent_path=os_path_dirname(project_path), enable_log=ena_log)
            cae.chk(21, bool(prj_path), f"failed to clone {origin_url} to {project_path}")
            cae.dpo(f"    - cloned {origin_url} repo (from fork {upstream_url}) to {prj_path}")

            if action == 'created':
                git_renew_remotes(project_path, origin_url, upstream_url=upstream_url,
                                  origin_name=origin_name, upstream_name=upstream_name, remotes=remote_urls)
            else:
                _renew_forked()

        if branch := get_app_option(ini_pdv, 'branch'):
            cae.po(f"    # ignored --branch option! to create a new feature branch run: pjm -b {branch} renew_project")

        cae.po(f" ==== {action} forked repository from {upstream_name} onto {origin_name} and at {project_path=}")

    @_action(PARENT_PRJ, ROOT_PRJ)
    def push_children(self, ini_pdv: ProjectDevVars, *children_pdv: ProjectDevVars):
        """ push specified children projects to the origin remote. """
        for chi_pdv in children_pdv:
            self.push_project(chi_pdv)
            if chi_pdv != children_pdv[-1]:
                _wait(ini_pdv)
        cae.po(f" ==== pushed {children_desc(ini_pdv, children_pdv)}")

    @_action(*ANY_PRJ_TYPE, shortcut='push')
    def push_project(self, ini_pdv: ProjectDevVars):
        """ push current/specified branch of project/package version-tagged to the remote host domain.

        :param ini_pdv:             project dev vars.
        """
        _check_action(ini_pdv, self.push_project)

        project_path = ini_pdv['project_path']
        origin_name = ini_pdv['REMOTE_ORIGIN']
        remote_urls = ini_pdv.pdv_val('remote_urls')
        owner_project = owner_project_from_url(remote_urls[origin_name])

        changed = git_uncommitted(project_path)
        cae.chk(17, not changed, f"{owner_project} has {len(changed)} uncommitted files: {changed}")

        if not self.repo_obj(0, owner_project):
            errors = self.init_new_remote_repo(ini_pdv)
            if errors:
                cae.po(f" **** errors in initializing git repository before push to remote {owner_project}:")
                cae.po(errors)
                return
        elif err_list := _update_project(ini_pdv, remote_names=remote_urls):
            cae.po(f" **** errors in updating project before pushing it to remote {owner_project}")
            cae.po(ppp(err_list))
            return

        branch_name = get_branch(ini_pdv)

        push_refs = [ini_pdv['MAIN_BRANCH']]

        if branch_name and branch_name not in push_refs:
            push_refs.append(branch_name)

        push_refs.append(_check_and_add_version_tag(ini_pdv))

        repo_url = git_push_url(ini_pdv, authenticate=True)
        output = git_push(project_path, repo_url, "--set-upstream", *push_refs)
        if output and output[0].startswith(EXEC_GIT_ERR_PREFIX):
            cae.po(f" **** errors in pushing project to remote {owner_project}")
            cae.po(ppp(output))
            return
        if output and debug_or_verbose():
            cae.po(ppp(output))

        output = git_fetch(project_path, origin_name)   # because pushed to reop_url (w/ token) instead of origin_name
        if output:
            cae.po(f" #### errors in fetching from origin after successful push of project to remote {owner_project}")
            cae.po(ppp(output))

        cae.po(f" ==== pushed {' '.join(push_refs)} branches/tags to remote project {owner_project}")

    @_action(PARENT_PRJ, ROOT_PRJ)
    def release_children(self, ini_pdv: ProjectDevVars, *children_pdv: ProjectDevVars):
        """ release the latest versions of the specified parent/root children projects to the origin remote. """
        for chi_pdv in children_pdv:
            cae.po(f" ---  {chi_pdv['project_name']}  ---  {chi_pdv['project_title']}")
            self.release_project(chi_pdv, 'LATEST')
            if chi_pdv != children_pdv[-1]:
                _wait(ini_pdv)
        cae.po(f" ==== released {children_desc(ini_pdv, children_pdv)}")

    @_action(*ANY_PRJ_TYPE, arg_names=(("version-tag", ), ('LATEST', )), shortcut='release')
    def release_project(self, ini_pdv: ProjectDevVars, version_tag: str):
        """ update local main branch from origin, optionally release (to PyPI if pip_name is set) and mirror to GitHub.

        :param ini_pdv:         project dev vars.
        :param version_tag:     push version tag in the format ``v<version-number>`` to release or ``LATEST`` to use
                                the version tag of the latest git repository version.
        """
        _check_action(ini_pdv, self.release_project)

        msg = self.repo_release_project(ini_pdv, version_tag)

        with in_os_env(start_dir=ini_pdv['project_path']):
            for mirror_remote in get_mirror_urls(ini_pdv):
                update_mirror(ini_pdv, mirror_remote)           # mirror this gitlab.com-hosted project onto GitHub
                msg += f"\n      and updated mirror {mask_token(mirror_remote)}"

        cae.po(msg)

    @_action(PARENT_PRJ, ROOT_PRJ)
    def request_children_merge(self, ini_pdv: ProjectDevVars, *children_pdv: ProjectDevVars):
        """ request specified children merge of a parent/namespace on the upstream/forked remote. """
        for chi_pdv in children_pdv:
            cae.po(f" ---  {chi_pdv['project_name']}  ---  {chi_pdv['project_title']}")
            self.request_merge(chi_pdv)
            if chi_pdv != children_pdv[-1]:
                _wait(ini_pdv)
        cae.po(f" ==== requested merge of {children_desc(ini_pdv, children_pdv)}")

    @_action(*ANY_PRJ_TYPE, shortcut='request')
    def request_merge(self, ini_pdv: ProjectDevVars):
        """ request merge of the origin=fork repository into the main branch at the upstream/forked remote. """
        _check_action(ini_pdv, self.request_merge)

        # https://docs.gitlab.com/ee/api/merge_requests.html#create-mr and https://stackoverflow.com/questions/51104622
        src_prj, tgt_prj, forked, branch = self.repo_merge_src_dst_fork_branch(ini_pdv)

        if TYPE_CHECKING:
            assert isinstance(src_prj, Project)
            assert isinstance(tgt_prj, Project)

        project_path = ini_pdv['project_path']
        commit_msg_file = check_commit_msg_file(project_path, 'pjm', prepare_commit, " to create a commit message file",
                                                commit_msg_file=ini_pdv['COMMIT_MSG_FILE_NAME'])
        commit_msg = read_file(commit_msg_file)
        try:
            merge_req = src_prj.mergerequests.create({
                'project_id': tgt_prj.id,
                'source_project_id': src_prj.id,
                'source_branch': branch,
                'target_project_id': tgt_prj.id,
                'target_branch': ini_pdv['MAIN_BRANCH'],
                'title': commit_msg.split(os.linesep)[0],
                # 'remove_source_branch': False,
                # 'force_remove_source_branch': False,
                # 'allow_collaboration': True,
                # 'subscribed': True,
            })
            if debug_or_verbose():
                cae.po(f"    . merge request diffs: {PPF([_.attributes for _ in merge_req.diffs.list()])}")

            action = " ==== requested merge"
            if not forked:
                retries = self.merge_pushed_project(ini_pdv, request=merge_req, message=commit_msg, max_wait=9)
                action = " ==== auto-merged unforked merge request" if retries else " **** failed merge request retries"

        except (GitlabError, GitlabHttpError, Exception) as ex:     # pylint: disable=broad-exception-caught
            action = f" **** exception {ex} on merge request"

        cae.po(f"{action} of branch {branch} from fork/origin ({src_prj=}) into forked/upstream ({tgt_prj=})")

    @_action(*ANY_PRJ_TYPE, arg_names=((), ('fragment', ), ))
    def search_repos(self, ini_pdv: ProjectDevVars, fragment: str = ""):
        """ search remote repositories via a text fragment in its project name/description. """
        fragment = fragment or ini_pdv['project_name']
        if not self.connection:
            cae.po(f" **** no connection (wrong credentials?) to search repositories at {ini_pdv['repo_domain']}")
            return

        repos = self.connection.projects.list(search=fragment, get_all=True)
        cae.po(f"----  found {len(repos)} repos containing '{fragment}' in its name project name or description:")
        for repo in repos:
            cae.po(f"    - {PPF(repo)}")
        cae.po(f" ==== searched all repos at {get_host_domain(ini_pdv)} for '{fragment}'")

    @_action(PARENT_PRJ, ROOT_PRJ)
    def show_children_status(self, ini_pdv: ProjectDevVars, *children_pdv: ProjectDevVars):
        """ display the local and remote status of parent/root children repos. """
        if not children_pdv:
            cae.po(" ==== no matching children found to show status for")
            return

        for chi_pdv in children_pdv:
            self.show_status(chi_pdv)
        cae.po(f" ==== displayed the status info of {children_desc(ini_pdv, children_pdv)}")

    @_action(arg_names=(('owner|group|user/project_name', ), ), shortcut='remote')
    def show_remote(self, _ini_pdv: ProjectDevVars, owner_project_path: str):
        """ display properties of any remote repository, specified via the owner (user|group) and project name path. """
        cae.po(f"   -- {owner_project_path} remote repository attributes:")
        prj_instance = self.repo_obj(0, owner_project_path)
        if prj_instance is None or not _show_remote_gitlab(prj_instance):
            cae.po(f"***** project {owner_project_path} unavailable via the remote server connection {self.connection}")
        else:
            cae.po(f" ==== dumped remote repository info of {owner_project_path}")

    @_action(PARENT_PRJ, *ANY_PRJ_TYPE, shortcut='status')
    def show_status(self, ini_pdv: ProjectDevVars):
        """ show git status of the specified/current project locally and on remote. """
        for remote_name, remote_url in ini_pdv.pdv_val('remote_urls').items():
            if owner_prj := self.repo_obj(0, owner_project_from_url(remote_url)):
                cae.po(f"  --- {remote_name} remote attributes at {remote_url}")
                _show_remote_gitlab(owner_prj, branch=git_current_branch(ini_pdv['project_path']))
            elif debug_or_verbose():
                cae.po(f"    # {remote_name} repository unavailable at {remote_url}")

        # print status to console, apart from the summary/last line which gets returned
        cae.po("=" + _show_status(ini_pdv)[1:])   # replace space char with '=' to make it a real end of action printout


def web_app_version(connection: PythonanywhereApi) -> str:
    """ determine the version of a deployed django project package.

    :param connection:      established connection to the *.pythonanywhere.com server.
    :return:                version string of the package deployed to the web host/server
                            or empty string if package version file or version-in-file not found.
    """
    init_file_content = connection.deployed_file_content(os_path_join(connection.project_name, PY_INIT))
    return "" if init_file_content is None else code_version(init_file_content)


class PythonanywhereCom(RemoteHost):
    """ remote actions on remote web host pythonanywhere.com (to be specified by --web_domain option). """
    connection: PythonanywhereApi               #: requests http connection
    var_prefix: str = 'web_'                    #: config variable name prefix

    def connect(self, ini_pdv: ProjectDevVars) -> bool:
        """ connect to www. and eu.pythonanywhere.com web host.

        :param ini_pdv:         parent/root project dev vars.
        :return:                boolean True on successful authentication else False.
        """
        self.connection = PythonanywhereApi(ini_pdv['web_domain'],
                                            ini_pdv['web_user'],
                                            ini_pdv.pdv_val('web_token'),
                                            ini_pdv.pdv_val('project_name'))
        return not self.connection.error_message

    deploy_flags = {'ALL': False, 'CLEANUP': False, 'LEAN': False, 'MASKS': []}
    """ optional flag names and default values for the actions :meth:`check_deploy` and :meth:`deploy_project` """

    # pylint: disable-next=too-many-locals,too-many-branches,too-many-statements
    def deploy_differences(self, ini_pdv: ProjectDevVars, action: str, version_tag: str, **optional_flags
                           ) -> tuple[str, str, set[str], set[str]]:
        """ determine differences between the specified repository and web host/server (deployable and deletable files).

        :param ini_pdv:         project dev vars.
        :param action:          pass 'check' to only check the differences between the specified repository and
                                the web server/host, or 'deploy' to prepare the deployment of these differences.
        :param version_tag:     project package version to deploy. pass ``LATEST`` to use the version tag
                                of the latest repository version (PyPI release), or ``WORKTREE`` to deploy
                                from the actual local project package version (including unstaged/untracked files).
        :param optional_flags:  optional command line arguments, documented in detail in the declaration of
                                the action method parameter :paramref:`check_deploy.optional_flags`.
        :return:                tuple of 2 strings and 2 sets. the first string contains a description of the project
                                and the server to check/deploy-to, and the second the path to the project root folder.
                                the two sets containing project file paths, relative to the
                                local/temporary project root folder, the first one with the deployable files,
                                and the 2nd one with the removable files.
        """
        prj_desc = f"{ini_pdv['web_user']}@{ini_pdv['web_domain']}/{ini_pdv['project_title']}"
        func = self.check_deploy if action == 'check' else self.deploy_project
        lean_msg = ' lean' if optional_flags['LEAN'] else ''
        verbose = debug_or_verbose()
        deployed_ver = web_app_version(self.connection)
        cae.po(f" ---- {action} {version_tag}{lean_msg} against host/project {prj_desc} {deployed_ver}")

        project_path = ini_pdv['project_path']
        prefix = ini_pdv['VERSION_TAG_PREFIX']
        if version_tag == 'WORKTREE':
            include_untracked = True
            branch_or_tag = prefix + deployed_ver if deployed_ver else ini_pdv['MAIN_BRANCH']
            # add "w" suffix to version number (only visible in logs)
            version_tag = prefix + latest_remote_version(ini_pdv, increment_part=0) + "w"
        else:
            include_untracked = False
            if version_tag == 'LATEST':
                version_tag = prefix + latest_remote_version(ini_pdv, increment_part=0)
            else:
                cae.chk(85, version_tag[0] == prefix and version_tag.count(".") == 2,
                        f"expected 'LATEST', 'WORKTREE' or a project version, e.g. {prefix}0.3.6, got '{version_tag}'")
                cae.chk(85, not deployed_ver or version_tag[1:] in (deployed_ver, increment_version(deployed_ver)),
                        f"too big increment between old|deployed ({deployed_ver}) and new version ({version_tag[1:]})"
                        + hint('pjm', func, " with the correct version or add --force to skip this version check"))
            project_path = git_clone(ini_pdv['repo_root'], ini_pdv['project_name'], "--filter=blob:none",
                                     branch_or_tag=version_tag)
            cae.chk(85, bool(project_path), "git clone tmp cleanup error, to check run again with the -D 1 option")
            branch_or_tag = f"{prefix}{deployed_ver}...{version_tag}"

        path_masks = optional_flags['MASKS'] + ['manage.py'] + root_packages_masks(ini_pdv.pdv_val('project_packages'))
        cae.vpo(f"  --- {len(path_masks)} deploy file path masks found: {ppp(sorted(path_masks))}")

        skip_func = skip_files_lean_web if lean_msg else skip_py_cache_files
        skipped = set()

        def _track_skipped(file_path: str) -> bool:
            if skip_func(file_path):
                if skip_py_cache_files(file_path):
                    return True
                skipped.add(file_path)
            return False
        deployable = relative_file_paths(project_path, path_masks, skip_file_path=_track_skipped)
        cae.vpo(f"  --- {len(deployable)} deployable project files found: {ppp(sorted(deployable))}")
        cae.vpo(f"  --- {len(skipped)}{lean_msg} project files got skipped: {ppp(sorted(skipped))}")

        to_deploy = deployable - skipped
        to_delete = set()
        which_files = "deployable"
        if deployed_ver and not optional_flags['ALL']:
            which_files = "new|changed|deleted"
            changed = git_branch_files(project_path, branch_or_tag=branch_or_tag, untracked=include_untracked,
                                       skip_file_path=skip_func)
            cae.vpo(f"  --- {len(changed)} changed project files found in {branch_or_tag}: {ppp(sorted(changed))}")
            to_deploy &= changed
            to_delete = set(paths_match(changed, path_masks)) - deployable

        for pkg_file_path in sorted(to_deploy):
            src_path = os_path_join(project_path, pkg_file_path)
            src_content = read_file(src_path, extra_mode='b') if os_path_isfile(src_path) else None
            dst_content = self.connection.deployed_file_content(pkg_file_path)
            if src_content == dst_content:
                dif = "is missing on both, repository and server" if src_content is None else "is identical on server"
                to_deploy.remove(pkg_file_path)
            elif src_content is None:                   # should never happen
                dif = f"need to be deleted on server (size={len(dst_content)})"
                to_delete.add(pkg_file_path)
                to_deploy.remove(pkg_file_path)
            elif dst_content is None:
                dif = f"is missing on server(size={len(src_content)})"
            else:
                dif = f"need to be upgraded on server (file size repo={len(src_content)} server={len(dst_content)})"
                if verbose:
                    dif += ":" + bytes_file_diff(dst_content, src_path, line_sep=os.linesep + " " * 6) + os.linesep
            cae.po(f"  --= {pkg_file_path: <45} {dif}")

        to_cleanup = set()
        if optional_flags['CLEANUP']:
            def _cleanup_speedup_skipper(file_path: str) -> bool:
                return skip_func(file_path) or bool(set(paths_match([file_path], DJANGO_EXCLUDED_FROM_CLEANUP)))
            to_cleanup = self.connection.deployed_code_files(['**/*'] if optional_flags['ALL'] else path_masks,
                                                             skip_file_path=_cleanup_speedup_skipper)
            cae.vpo(f"  --- {len(to_cleanup)} removable files found on {self.connection.project_name} project server:"
                    f" {ppp(sorted(to_cleanup))}")
            to_cleanup -= (deployable - skipped)
            if not to_cleanup:
                cae.po("  --- no extra files to clean up found on server")
            else:
                cae.po(f"  --- {len(to_cleanup)} deletable{lean_msg} files: {ppp(sorted(to_cleanup))}" + hint(
                    'pjm', func, " to remove them from the server") if action == 'check' else "")

        cae.chk(85, bool(to_deploy | to_delete | to_cleanup), f"no {which_files}|cleanup files found in {version_tag}"
                + hint('pjm', func, f" specifying ALL as extra argument to {action} all deployable project files"))

        verbose = action == 'check' or verbose
        cae.po(f" ===  {len(to_deploy)} {which_files} files found to migrate server to {version_tag} version"
               f"{'; from v' + deployed_ver if deployed_ver else ''}{':' + ppp(sorted(to_deploy)) if verbose else ''}")
        cae.po(f" ===  {len(to_delete) + len(to_cleanup)} deletable (repo={len(to_delete)} cleanup={len(to_cleanup)})"
               f" files found{':' + ppp(sorted(to_delete | to_cleanup)) if verbose else ''}")

        return prj_desc, project_path, to_deploy, to_delete | to_cleanup

    # ----------- remote action methods ----------------------------------------------------------------------------

    @_action(APP_PRJ, DJANGO_PRJ, arg_names=(("version-tag", ), ('LATEST', ), ('WORKTREE', ), ), flags=deploy_flags)
    def check_deploy(self, ini_pdv: ProjectDevVars, version_tag: str, **optional_flags):
        """ check all project package files at the app/web server against the specified package version.

        :param ini_pdv:         project dev vars.

        :param version_tag:     version tag in the format ``v<version-number>`` to check or ``LATEST`` to check against
                                the latest repository version or ``WORKTREE`` to check directly against
                                the local work tree (with the locally added, unstaged and changed files).

        :param optional_flags:  additional/optionally supported command line arguments:

                                * ``ALL`` is including all deployable package files, instead of only the new, changed or
                                  deleted files in the specified repository.
                                * ``CLEANUP`` is checking for deletable files on the web server/host, e.g., after
                                  they got removed from the specified repository or work tree.
                                * ``LEAN`` is reducing the deployable files sets to the minimum (using e.g., the
                                  function :func:`skip_files_lean_web`), like e.g., the gettext ``.po`` files,
                                  the ``media_ini`` root folder and the ``static`` subfolder with the initial static
                                  files of the web project.
                                * ``MASKS`` specifies a list of file paths masks/pattern to be included in the
                                  repository files to check/deploy. to include e.g., the files of the static root folder
                                  specify this argument as ``MASKS="['static/**/*']"``. single files can be included
                                  too, by adding their possible file names to the list - only the found ones will be
                                  included. for example, to include the django database, you could add some possible DB
                                  file names to the list like in ``"MASKS=['static/**/*', 'db.sqlite', 'project.db']"``
        """
        prj_desc, _, to_deploy, to_delete = self.deploy_differences(ini_pdv, 'check', version_tag, **optional_flags)

        cae.po(f" ==== found {len(to_deploy)} outdated and {len(to_delete)} deletable files on host/project {prj_desc}")

    @_action(APP_PRJ, DJANGO_PRJ, arg_names=(("version-tag", ), ('LATEST', ), ('WORKTREE', ), ), flags=deploy_flags,
             shortcut='deploy')
    def deploy_project(self, ini_pdv: ProjectDevVars, version_tag: str, **optional_flags):
        """ deploy code files of a django/app project version to the web-/app-server.

        :param ini_pdv:         project dev vars.
        :param version_tag:     version tag in the format ``v<version-number>`` to deploy or ``LATEST`` to use
                                the tag of the latest repository version or ``WORKTREE`` to deploy directly
                                from the local work tree (including locally added, unstaged and changed files).
        :param optional_flags:  optional command line arguments, documented in the :meth:`.check_deploy` action.
        """
        prj_desc, root, to_deploy, to_delete = self.deploy_differences(ini_pdv, 'deploy', version_tag, **optional_flags)

        for upg_fil in to_deploy:
            err_str = self.connection.deploy_file(upg_fil, read_file(os_path_join(root, upg_fil), extra_mode='b'))
            cae.chk(96, not err_str, err_str)

        for del_fil in to_delete:
            err_str = self.connection.delete_file_or_folder(del_fil)
            cae.chk(96, not err_str, err_str)

        if to_deploy:
            cae.po(f"  === {len(to_deploy)} files deployed: {ppp(sorted(to_deploy))}")
        if to_delete:
            cae.po(f"  === {len(to_delete)} files removed: {ppp(sorted(to_delete))}")
        if to_deploy or to_delete:
            cae.po("  === check server if Django manage migration command(s) have to be run and if a restart is needed")
        cae.po(f" ==== successfully deployed {version_tag} to host/project {prj_desc}")


# --------------- local actions ---------------------------------------------------------------------------------------


@_action(PARENT_PRJ, ROOT_PRJ, arg_names=tuple(tuple(('source-name', 'rel-path', ) + _) for _ in ARGS_CHILDREN_DEFAULT))
def add_children_file(ini_pdv: ProjectDevVars, file_name: str, rel_path: str, *children_pdv: ProjectDevVars) -> bool:
    """ add any file to the project working trees of parent/root and children/portions.

    :param ini_pdv:             parent/root project dev vars.
    :param file_name:           source (template) file name (optional with a path).
    :param rel_path:            destination path relative to the project root.
    :param children_pdv:        project dev vars of the children to process.
    :return:                    boolean True if the file got added to the parent/root and to all children, else False.
    """
    added = []
    is_root = ini_pdv['project_type'] == ROOT_PRJ
    if is_root and add_file(ini_pdv, file_name, rel_path):
        added.append(ini_pdv['project_name'])

    for chi_pdv in children_pdv:
        if add_file(chi_pdv, file_name, rel_path):
            added.append(chi_pdv['project_name'])

    cae.po(f" ==== added {len(added)}/{len(children_pdv)} times {file_name} into {rel_path} for: {added}")
    return len(added) == (1 if is_root else 0) + len(children_pdv)


@_action(*ANY_PRJ_TYPE, arg_names=(('source-name', 'rel-path', ), ('source-name', ), ))
def add_file(ini_pdv: ProjectDevVars, file_name: str, rel_path: str = ".") -> bool:
    """ add any file into the project working tree.

    :param ini_pdv:             project dev vars.
    :param file_name:           file name to add (either with an absolut path, or relative to the project root).
                                if the source is a template file, then the path prefixes of the base file name will be
                                processed (with the project dev vars as template vars).
    :param rel_path:            optional relative folder/dir path in the destination project working tree, defaults
                                to the project root folder.
    :return:                    boolean True if the file got added to the specified project, else False.
    """
    project_path = ini_pdv['project_path']
    file_name = os_path_join(project_path, file_name)
    dst_dir = os_path_join(project_path, rel_path)
    rel_file = os_path_join(rel_path, os_path_basename(file_name))
    if not os_path_isfile(file_name) or not os_path_isdir(dst_dir):
        cae.dpo(f" #### either source file {file_name} or destination folder {dst_dir} does not exist")
        return False
    if os_path_isfile(os_path_join(project_path, rel_file)):
        cae.dpo(f" #### file not added because the destination file {rel_file} does exist already")
        return False

    with in_prj_dir_venv(project_path):
        dst_file_name = deploy_template(file_name, dst_path=rel_file, patcher='pjm.add_file action',
                                        prefixes_parsers=PATH_PREFIXES_PARSERS, tpl_vars=ini_pdv)

    if not dst_file_name:
        cae.dpo(f"  ### the source file {file_name} could not be added to {rel_path}")
    else:
        cae.po(f" ==== added {dst_file_name} to {ini_pdv['project_title']}")
    return bool(dst_file_name)


@_action(APP_PRJ, shortcut='build', flags={'LIBS': False, 'EMBED': False})
def build_gui_app(ini_pdv: ProjectDevVars, **build_flags):  # pylint: disable=too-many-locals
    """ build gui app with buildozer, add LIBS to make a clean/full build and EMBED to include APK to share. """
    extra_args = []
    apk_ext = ".{apk_ext}"  # mask/camouflage APK extension for buildozer/P4A to embed APK

    if cae.verbose or get_app_option(ini_pdv, 'more_verbose'):
        extra_args.append('-v')

    extra_args += ['android', 'debug']
    output: list[str] = [f" ---  buildozer arguments: {extra_args}"]    # non-empty list to keep stderr/stdout merged
    with in_prj_dir_venv(ini_pdv['project_path']):
        if build_flags['LIBS'] and os_path_isdir('.buildozer'):
            cae.po("  --- removing local .buildozer folder")
            shutil.rmtree('.buildozer', ignore_errors=True)

        for old_apk in reversed(glob.glob(os_path_join(MOVES_SRC_FOLDER_NAME + "*", "*" + apk_ext))):
            cae.po(f"   -- removing {old_apk=} from the previous build")
            os.remove(old_apk)
            apk_dir = os_path_dirname(old_apk)
            break
        else:
            apk_dir = MOVES_SRC_FOLDER_NAME + UPDATER_ARGS_SEP + UPDATER_ARG_OS_PLATFORM + 'android'

        sh_exit_if_exec_err(120, "buildozer", extra_args=extra_args, lines_output=output, exit_on_err=False)

        in_filters = ('% Loading', '% Fetch', '% Computing', '% Installing', '% Downloading', '% Unzipping',
                      'Compressing objects:', 'Counting objects:', 'Enumerating objects:', 'Finding sources:',
                      'Receiving objects:', 'Resolving deltas:')
        start_filters = ('     |', '   ━', '   ╸', '- Download ')
        strip_esc = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')  # https://stackoverflow.com/questions/75904146
        log_lines = []
        for lines in output:
            for line in lines.split('\r'):              # split %-progress lines (separated only with CR)
                sl = strip_esc.sub('', line)            # remove coloring/formatting ANSI escape sequences
                if sl and not (any(_ in sl for _ in in_filters) or any(sl.startswith(_) for _ in start_filters)):
                    log_lines.append(sl)

        log_file = 'build_log.txt'
        write_file(log_file, os.linesep.join(log_lines))

        success = log_lines[-1].endswith("available in the bin directory")
        for line_no in range(-2 if success else -201, 0):
            cae.po(" " * 6 + log_lines[line_no])

        if success and build_flags['EMBED']:
            new_apk = log_lines[-1].split(" ")[2]   # == "# APK <app_name-version>.apk available in the bin directory"
            file_name = os_path_splitext(new_apk)[0]

            os.makedirs(apk_dir, exist_ok=True)
            # noinspection PyTypeChecker
            copy_file(os_path_join("bin", new_apk), os_path_join(apk_dir, file_name + apk_ext))
            slim_apk = os_path_join("bin", file_name + "_slim.apk")
            if os_path_isfile(slim_apk):
                os.remove(slim_apk)     # without this move_file() would fail on MSWin if slim_apk already exists
            move_file(os_path_join("bin", new_apk), slim_apk)

            cae.po(f"   == compile apk embedding APK at {datetime.datetime.now()}")

            sh_exit_if_exec_err(123, "buildozer", extra_args=extra_args, exit_on_err=False)

            cae.po(f"  === embedded {slim_apk=} into APK in {apk_dir}/ at {datetime.datetime.now()}")

    cae.po(f" ==== {ini_pdv['project_title']} {'successfully' if success else 'NOT'} built;"
           f" see {log_file} ({len(log_lines)} lines) for details{chr(7)}")


@_action(PARENT_PRJ, ROOT_PRJ)
def check_children_integrity(parent_pdv: ProjectDevVars, *children_pdv: ProjectDevVars):
    """ run integrity checks for the specified children of a parent or portions of a namespace. """
    for chi_pdv in children_pdv:
        cae.po(f"  --- integrity check of {chi_pdv['project_title']}")
        check_integrity(chi_pdv)

    cae.po(f" ==== passed integrity checks of {children_desc(parent_pdv, children_pdv)}")


@_action(*ANY_PRJ_TYPE, shortcut='check')
def check_integrity(ini_pdv: ProjectDevVars):
    """ integrity check of files/folders completeness, managed/template files update-state, and CI tests. """
    project_type = ini_pdv['project_type']
    project_path = ini_pdv['project_path']
    if project_type in (NO_PRJ, PARENT_PRJ):
        cae.po(f" ==== no checks for {project_type or 'undefined'} project at {project_path}")
        return

    _check_folders_files_completeness(ini_pdv)
    if not on_ci_host():
        with in_prj_dir_venv(project_path):
            check_templates(cae, ini_pdv, fail_on_outdated=True)
    _check_resources(ini_pdv)
    _check_types_linting_tests(ini_pdv)
    cae.po(f" ==== passed integrity checks for {ini_pdv['project_title']}")


@_action(PARENT_PRJ, ROOT_PRJ, arg_names=(('children-owner-name-versions' + ARG_MULTIPLES, ), ),
         pre_action=_check_children_to_clone)
def clone_children(parent_or_root_pdv: ProjectDevVars, *owner_name_versions: str) -> list[str]:
    """ clone specified namespace-portion/parent-child repositories to the local machine.

    .. hint:: the supported command line options are documented in the :func:`clone_project` action.

    :param parent_or_root_pdv:  parent/namespace-root project to clone from.
    :param owner_name_versions: the projects/packages/portions to be cloned, identified by their repository owner
                                user|group, the project/portion name and an optional version::

                                    group-name/project_name1==v3.6.9 project_name2 ...

                                running in namespace root/sister project allows to only specify the portion names::

                                    portion_name1 portion_name2 ...

                                the user|group name is only obligatory when this action got started from a parent folder
                                (else it defaults to owner of the namespace root|sister project).
    :return:                    cloned children project paths list (for :func_`clone_children` and unit testing).
    """
    project_type = parent_or_root_pdv['project_type']
    cae.chk(57, project_type in (PARENT_PRJ, ROOT_PRJ),
            f"no root|parent project found at the specified project path {parent_or_root_pdv['project_path']}")

    project_paths = []
    for own_nam_ver in owner_name_versions:
        project_paths.append(clone_project(parent_or_root_pdv, own_nam_ver))

    cae.po(f" ==== {len(project_paths)} projects cloned: {ppp(project_paths)}")
    return project_paths


@_action(ROOT_PRJ, PARENT_PRJ,
         arg_names=((f"project-owner-name[{PROJECT_VERSION_SEP}version]", ), ),
         pre_action=_check_children_to_clone, shortcut='clone')
def clone_project(ini_pdv: ProjectDevVars, owner_name_version: str) -> str:
    """ clone remote repo to the local machine.

    the origin host domain can be specified with the --repo_domain option.
    the owner user|group name can alternatively be specified via the --repo_group option.
    if the --branch option is specified, then only this branch/tag will be cloned (quicker!) and directly checked-out.
    extra checks on the correct portion/project name can be activated by specifying the --namespace_name option.

    :param ini_pdv:             project vars, for path, owner and namespace defaults, either manually prepared for the
                                project to clone or use the local parent or namespace root/sister project.
    :param owner_name_version:  name of the project to clone, optionally prefixed with the owner name (and a slash)
                                and suffixed with (the :data:`PROJECT_VERSION_SEP` seperator and) a version number.
    :return:                    project path of the cloned project or an empty string if an error occurred.
                                needed/used by :func:`clone_children` and unit tests.
    """
    project_path = ini_pdv['project_path']
    parent_path = project_path if ini_pdv['project_type'] == PARENT_PRJ else os_path_dirname(project_path)
    req_branch = cast(str, get_app_option(ini_pdv, 'branch')) or ""
    project_owner, project_name, project_version = project_owner_name_version(
        owner_name_version, owner_default=ini_pdv['repo_group'], namespace_default=ini_pdv['namespace_name'])
    branch_or_version = ini_pdv['VERSION_TAG_PREFIX'] + project_version if project_version else req_branch
    repo_root = f"{ini_pdv['REPO_HOST_PROTOCOL']}{get_host_domain(ini_pdv)}/{project_owner}"

    project_path = git_clone(repo_root, project_name, branch_or_tag=branch_or_version, parent_path=parent_path,
                             enable_log=bool(get_app_option(ini_pdv, 'git_log')))

    if project_path and req_branch:
        git_checkout(project_path, new_branch=req_branch, force=bool(get_app_option(ini_pdv, 'force')))
        owner_name_version += f" (branch: {req_branch})"

    if project_path:
        cae.po(f" ==== cloned project {owner_name_version} from {repo_root} into project path {project_path}")
    else:
        cae.po(f" **** failed to clone {branch_or_version=} of {owner_name_version} from {repo_root}/{project_name}")

    return project_path


@_action(PARENT_PRJ, ROOT_PRJ, pre_action=check_children_integrity)
def commit_children(ini_pdv: ProjectDevVars, *children_pdv: ProjectDevVars):
    """ commit changes to children of a namespace/parent using the individually prepared commit message files. """
    for chi_pdv in children_pdv:
        cae.po(f" ---  {chi_pdv['project_name']}  ---  {chi_pdv['project_title']}")
        commit_project(chi_pdv)
    cae.po(f" ==== committed {children_desc(ini_pdv, children_pdv)}")


@_action(*ANY_PRJ_TYPE, pre_action=check_integrity, shortcut='commit')
def commit_project(ini_pdv: ProjectDevVars):
    """ commit changes of a single project to the local repo using the prepared commit message file. """
    _check_action(ini_pdv, commit_project)

    project_path = ini_pdv['project_path']

    git_init_add(ini_pdv)
    git_commit(project_path, ini_pdv['project_version'], commit_msg_file=ini_pdv['COMMIT_MSG_FILE_NAME'])

    cae.po(f" ==== committed {ini_pdv['project_title']}")


@_action(PARENT_PRJ, ROOT_PRJ, arg_names=tuple(tuple(('file-or-folder-name', ) + _) for _ in ARGS_CHILDREN_DEFAULT))
def delete_children_file(ini_pdv: ProjectDevVars, file_name: str, *children_pdv: ProjectDevVars) -> bool:
    """ delete a file or an empty folder from parent/root and children/portions project roots.

    :param ini_pdv:             parent/root project dev vars.
    :param file_name:           file/folder name to delete (optional with a path, relative to the project root).
    :param children_pdv:        tuple of children project dev vars.
    :return:                    boolean True if the file got found and deleted from the parent and all the children
                                projects, else False.
    """
    c_del = []
    is_root = ini_pdv['project_type'] == ROOT_PRJ
    if is_root and delete_file(ini_pdv, file_name):
        c_del.append(ini_pdv)

    for chi_pdv in children_pdv:
        if delete_file(chi_pdv, file_name):
            c_del.append(chi_pdv)

    cae.po(f" ==== deleted {file_name} in {children_desc(ini_pdv, children_pdv=c_del)}")
    return len(c_del) == (1 if is_root else 0) + len(children_pdv)


@_action(*ANY_PRJ_TYPE, arg_names=(('file-or-folder-name', ), ))
def delete_file(ini_pdv: ProjectDevVars, file_or_dir: str) -> bool:
    """ delete a file or an empty folder from the project.

    :param ini_pdv:             project dev vars.
    :param file_or_dir:         file/folder name to delete (optional with a path, relative to the project root).
    :return:                    boolean True if the file got found and deleted from the specified project, else False.
    """
    # git is too picky - does not allow deleting unstaged/changed files
    # project_path = ini_pdv['project_path']
    # with _in_prj_dir_venv(project_path):
    #     return sh_exit_if_git_err(89, f"git rm -f {os_path_relpath(file_or_dir, project_path)}",exit_on_err=False)==[]
    file_or_dir = os_path_join(ini_pdv['project_path'], file_or_dir)   # prj path ignored if file_or_dir is abs
    is_dir = os_path_isdir(file_or_dir)
    if not is_dir and not os_path_isfile(file_or_dir):
        cae.po(f"  *** {file_or_dir} to delete does not exist in {ini_pdv['project_title']}")
        return False

    if is_dir:
        os.rmdir(file_or_dir)
    else:
        os.remove(file_or_dir)

    if os_path_isdir(file_or_dir) if is_dir else os_path_isfile(file_or_dir):               # pragma: no cover
        cae.po(f"  *** error deleting {file_or_dir} from {ini_pdv['project_title']}")
        return False

    cae.po(f" ==== deleted {'folder' if is_dir else 'file'} {file_or_dir} in {ini_pdv['project_title']}")
    return True


@_action(PARENT_PRJ, ROOT_PRJ)
def install_children_editable(ini_pdv: ProjectDevVars, *children_pdv: ProjectDevVars):
    """ install parent children or namespace portions as editable on the local machine. """
    for chi_pdv in children_pdv:
        install_editable(chi_pdv)
    cae.po(f" ==== installed as editable {children_desc(ini_pdv, children_pdv)}")


@_action(*ANY_PRJ_TYPE, shortcut='editable')
def install_editable(ini_pdv: ProjectDevVars):
    """ install the project as editable from the source/project root folder. """
    with in_prj_dir_venv(project_path := ini_pdv['project_path']):
        sh_exit_if_exec_err(90, PIP_INSTALL_CMD, extra_args=["--editable", project_path],
                            exit_msg=f"package installation from local {project_path=} failed")

    cae.po(f" ==== installed as editable: {ini_pdv['project_title']}")


@_action()
def new_app(ini_pdv: ProjectDevVars) -> ProjectDevVars:
    """ create or complete/renew a gui app project. """
    return _renew_project(ini_pdv, APP_PRJ)


@_action(PARENT_PRJ, ROOT_PRJ)
def new_children(ini_pdv: ProjectDevVars, *children_pdv: ProjectDevVars) -> list[ProjectDevVars]:
    """ initialize or renew parent folder children or namespace portions. """
    new_vars = []
    for chi_pdv in children_pdv:
        cae.po(f" ---  {chi_pdv['project_name']}  ---  {chi_pdv['project_title']}")
        new_vars.append(renew_project(chi_pdv))
    cae.po(f" ==== renewed {children_desc(ini_pdv, children_pdv=new_vars)}")
    return new_vars


@_action()
def new_django(ini_pdv: ProjectDevVars) -> ProjectDevVars:
    """ create or complete/renew a django project. """
    return _renew_project(ini_pdv, DJANGO_PRJ)


@_action()
def new_module(ini_pdv: ProjectDevVars) -> ProjectDevVars:
    """ create or complete/renew a module project. """
    return _renew_project(ini_pdv, MODULE_PRJ)


@_action()
def new_namespace_root(ini_pdv: ProjectDevVars) -> ProjectDevVars:
    """ create or complete/renew a namespace root package. """
    return _renew_project(ini_pdv, ROOT_PRJ)


@_action()
def new_package(ini_pdv: ProjectDevVars) -> ProjectDevVars:
    """ create or complete/renew a package project. """
    return _renew_project(ini_pdv, PACKAGE_PRJ)


@_action()
def new_playground(ini_pdv: ProjectDevVars) -> ProjectDevVars:
    """ create or complete/renew a playground project. """
    return _renew_project(ini_pdv, PLAYGROUND_PRJ)


@_action(PARENT_PRJ, ROOT_PRJ, arg_names=tuple(tuple(('commit-message-title', ) + _) for _ in ARGS_CHILDREN_DEFAULT))
def prepare_children_commit(ini_pdv: ProjectDevVars, title: str, *children_pdv: ProjectDevVars):
    """ run code checks and prepare/overwrite the commit message file for a bulk-commit of children projects.

    :param ini_pdv:             parent/root project dev vars.
    :param title:               optional commit message title.
    :param children_pdv:        project dev var args tuple of the children to process.
    """
    for chi_pdv in children_pdv:
        cae.po(f" ---  {chi_pdv['project_name']}  ---  {chi_pdv['project_title']}")
        prepare_commit(chi_pdv, title=title)
    cae.po(f" ==== prepared commit of {children_desc(ini_pdv, children_pdv)}")


@_action(*ANY_PRJ_TYPE, arg_names=((), ('commit-message-title', ), ), shortcut='prepare')
def prepare_commit(ini_pdv: ProjectDevVars, title: str = ""):
    """ run code checks and prepare/overwrite the commit message file for the commit of a single project/package.

    :param ini_pdv:             project dev vars.
    :param title:               optional commit message title (with the f-string placeholder `{project_version}`).
    """
    _check_action(ini_pdv, prepare_commit, commit_project)

    git_init_add(ini_pdv)
    write_commit_message(ini_pdv, title=title)

    cae.po(f" ==== prepared commit of {ini_pdv['project_title']}")


@_action(PARENT_PRJ, ROOT_PRJ)
def refresh_children_managed(ini_pdv: ProjectDevVars, *children_pdv: ProjectDevVars):
    """ refresh managed files from templates in namespace/project-parent children projects. """
    for chi_pdv in children_pdv:
        cae.po(f" ---  {chi_pdv['project_name']}  ---  {chi_pdv['project_title']}")
        refresh_managed(chi_pdv)
    cae.po(f" ==== refreshed {children_desc(ini_pdv, children_pdv)}")


@_action(*ANY_PRJ_TYPE, shortcut='refresh')
def refresh_managed(ini_pdv: ProjectDevVars):
    """ refresh/renew all the managed files in the specified project. """
    project_path = ini_pdv['project_path']

    errors = update_frozen_req_files(ini_pdv)  # check|update frozen *requirements.txt
    cae.chk(41, not errors, f"frozen requirements files update errors:{ppp(errors)}")

    with in_prj_dir_venv(project_path):
        man = check_templates(cae, ini_pdv)
        if not man:
            return
        man.deploy()

    dst_files = list(dst_path for dst_path, mf in man.deploy_files.items() if not mf.up_to_date)
    dbg_msg = ": " + " ".join(os_path_relpath(_, project_path) for _ in dst_files) if debug_or_verbose() else ""
    cae.po(f" ==== refreshed {len(dst_files)} managed files in {ini_pdv['project_title']}{dbg_msg}")


@_action(PARENT_PRJ, ROOT_PRJ, arg_names=tuple(tuple(('old-name', 'new-name', ) + _) for _ in ARGS_CHILDREN_DEFAULT))
def rename_children_file(ini_pdv: ProjectDevVars, old_file_name: str, new_file_name: str, *children_pdv: ProjectDevVars
                         ) -> bool:
    """ rename a file or folder in parent/root and children/portions projects.

    :param ini_pdv:             parent/root project dev vars.
    :param old_file_name:       file/folder name to rename (optional with a path, relative to the project root).
    :param new_file_name:       new name of file/folder (optional with a path, relative to the project root).
    :param children_pdv:        project dev vars tuple of the children to process.
    :return:                    boolean True if the file got renamed in the parent and all the children projects,
                                else False.
    """
    ren = []
    if ini_pdv['project_type'] == ROOT_PRJ and rename_file(ini_pdv, old_file_name, new_file_name):
        ren.append(ini_pdv['project_name'])

    for chi_pdv in children_pdv:
        if rename_file(chi_pdv, old_file_name, new_file_name):
            ren.append(chi_pdv['project_name'])

    cae.po(f" ==== renamed {len(ren)}/{len(children_pdv) + 1} times {old_file_name} to {new_file_name} in: {ren}")
    return len(ren) == 1 + len(children_pdv)


@_action(*ANY_PRJ_TYPE, arg_names=(('old-file-or-folder-name', 'new-file-or-folder-name', ), ))
def rename_file(ini_pdv: ProjectDevVars, old_file_name: str, new_file_name: str) -> bool:
    """ rename a file or folder in the project tree.

    :param ini_pdv:             project dev vars.
    :param old_file_name:       source file/folder (optional with a path, absolute or relative to the project root).
    :param new_file_name:       destination file/folder (optional path, absolute or relative to the project root).
    :return:                    boolean True if the file/folder got renamed, else False.
    """
    old_file_name = os_path_join(ini_pdv['project_path'], old_file_name)   # prj path ignored if absolute
    new_file_name = os_path_join(ini_pdv['project_path'], new_file_name)
    if not os_path_isfile(old_file_name) or os_path_isfile(new_file_name):
        cae.po(f"  ### either source file {old_file_name} not found or destination {new_file_name} already exists")
        return False

    os.rename(old_file_name, new_file_name)     # using os.remove because git mv is too picky

    if os_path_isfile(old_file_name) or not os_path_isfile(new_file_name):              # pragma: no cover
        cae.po(f"  *** rename of {old_file_name} to {new_file_name} failed: old-exists={os_path_isfile(old_file_name)}")
        return False

    cae.po(f" ==== renamed file {old_file_name} to {new_file_name} in {ini_pdv['project_title']}")
    return True


@_action(PARENT_PRJ, ROOT_PRJ)
def renew_children(ini_pdv: ProjectDevVars, *children_pdv: ProjectDevVars):
    """ complete/renew/update the local children projects of the specified parent/namespace-root. """
    for chi_pdv in children_pdv:
        renew_project(chi_pdv)
    cae.po(f" ==== updated {children_desc(ini_pdv, children_pdv)}")


@_action(*ANY_PRJ_TYPE, shortcut='renew')
def renew_project(ini_pdv: ProjectDevVars) -> ProjectDevVars:
    """ complete/renew/update an existing project. """
    return _renew_project(ini_pdv, ini_pdv['project_type'])


@_action(PARENT_PRJ, ROOT_PRJ, arg_names=tuple(tuple(('command', ) + _) for _ in ARGS_CHILDREN_DEFAULT), shortcut='run')
def run_children_command(ini_pdv: ProjectDevVars, command: str, *children_pdv: ProjectDevVars):
    """ run console command for the specified portions/children of a namespace/parent.

    :param ini_pdv:             parent/root project dev vars.
    :param command:             console command string (including all command arguments).
    :param children_pdv:        tuple of children project dev vars.
    """
    for chi_pdv in children_pdv:
        cae.po(f"---   {chi_pdv['project_name']}   ---   {chi_pdv['project_title']}")

        output: list[str] = []
        with in_prj_dir_venv(chi_pdv['project_path']):
            sh_exit_if_exec_err(98, command, lines_output=output, exit_on_err=not get_app_option(ini_pdv, 'force'))
        cae.po(ppp(output)[1:])

        if chi_pdv != children_pdv[-1]:
            _wait(ini_pdv)

    cae.po(f" ==== run command '{command}' for {children_desc(ini_pdv, children_pdv)}")


@_action(local_action=False, shortcut='actions')    # local_action=False sets host_api to display remote actions
def show_actions(ini_pdv: ProjectDevVars):
    """ get available/registered/implemented actions info of the specified/current project and remote. """
    host_api = ini_pdv.pdv_val('host_api')
    repo_domain = get_host_domain(ini_pdv)
    actions = sorted(_available_actions())

    prefix = f"  --- found {len(actions)} available actions"
    if not get_app_option(ini_pdv, 'more_verbose'):    # compact output
        cae.po(prefix + "; add the --more_verbose (-v) option for action details:")
        for act_name in actions:
            if act_fun := _act_callable(host_api, act_name):
                cae.po(f"    - {act_fun.__name__: <30} {(act_fun.__doc__ or '').split(os.linesep)[0]}")

    else:
        cae.po(prefix + f" (locally and at {'|'.join(REGISTERED_HOSTS_CLASS_NAMES)}):")

        for act_name in actions:
            cae.po(f"    - {act_name} " + "-" * (120 - len(act_name)))
            for spec in _act_specs(act_name):
                _act_help_print(spec)

        if other_host_actions := [_ for _ in actions if not _act_callable(host_api, _)]:
            fail_msg = ("" if host_api.connection else f"(due to missing/wrong {mask_token(ini_pdv['repo_token'])=})"
                        ) if host_api else f"(due to invalid {repo_domain=})"
            # noinspection PyUnboundLocalVariable
            cae.po(f"  --- {len(other_host_actions)} actions registered but not available for this project {fail_msg}")
            cae.po(f"      {', '.join(other_host_actions)}")

    cae.po(f" ==== project manager actions for {ini_pdv['project_title']}")


@_action(PARENT_PRJ, ROOT_PRJ)
def show_children_versions(ini_pdv: ProjectDevVars, *children_pdv: ProjectDevVars):
    """ show package versions (local, remote and on pypi) for the specified children of a namespace/parent. """
    for chi_pdv in children_pdv:
        show_versions(chi_pdv)
    cae.po(f" ==== versions shown of {children_desc(ini_pdv, children_pdv)}")


@_action(*ANY_PRJ_TYPE, shortcut='versions')
def show_versions(ini_pdv: ProjectDevVars):     # pylint: disable=too-many-locals
    """ display package versions of worktree, remote repo(s), latest PyPI release and default app/web host. """
    project_path = ini_pdv['project_path']
    project_version = ini_pdv['project_version']
    tag_pattern = ini_pdv['VERSION_TAG_PREFIX'] + "*"

    msg = f" ==== local:{project_version: <9}"
    loc_tags = git_tag_list(project_path, tag_pattern=tag_pattern)
    if loc_tags and (tag := loc_tags[-1][1:]) != project_version:
        msg += ppp(loc_tags) if loc_tags[0].startswith(EXEC_GIT_ERR_PREFIX) else f" !=local-tag!:{tag: <9}"

    for remote_name in ini_pdv.pdv_val('remote_urls'):
        output = git_tag_list(project_path, remote=remote_name, tag_pattern=tag_pattern)
        msg += f" {remote_name}:{output[-1][1:] if output else '-': <9}"

    if pip_name := ini_pdv['pip_name']:
        pypi_test = ini_pdv['parent_folder'] == 'TsT'
        newest_ver = get_pypi_versions(pip_name, pypi_test=pypi_test)[-1] or '-'
        msg += f" pypi{'TsT' if pypi_test else ''}:{newest_ver: <9}"

    if ini_pdv['project_type'] == DJANGO_PRJ:
        web_domain = ini_pdv['web_domain']
        web_user = ini_pdv['web_user']
        if 'pythonanywhere.com' in web_domain and web_user:     # only if a default web host is defined in env/config
            web_token = get_host_user_token(ini_pdv, web_domain, host_user=web_user, var_prefix='web')
            connection = PythonanywhereApi(web_domain, web_user, web_token, ini_pdv['project_name'])
            msg += f" web:{web_app_version(connection): <9}"

    cae.po(msg)


@_action(*ANY_PRJ_TYPE, arg_names=(('mirror-url-or-remote-name', ), ), shortcut='mirror')
def update_mirror(ini_pdv: ProjectDevVars, mirror_remote: str):
    """ create or update a mirror of the actual repo onto the specified remote/host.

    :param ini_pdv:             project dev vars of the project to create/update a mirror/replication for.
    :param mirror_remote:       mirror remote name or server/host url (optionally with authentication) to push to.

    .. note::
        there are three more pushable (but currently not implemented) git ref namespaces: pull, pipelines and lfs.
        other git ref namespaces are stash and remotes (remotes cannot be pushed - therefore the git push option
        --mirror cannot be used to create&update a mirror at GitHub/GitLab).
    """
    url_parts = urlparse(mirror_remote)
    if url_parts.netloc:
        mirror_url = mirror_remote
    else:
        remotes = ini_pdv.pdv_val('remote_urls')
        if mirror_remote not in remotes:
            cae.po(f" **** invalid mirror remote name/url {mirror_remote}")
            return
        mirror_url = remotes[mirror_remote]
        url_parts = urlparse(mirror_url)

    if not (hostname := url_parts.hostname):
        cae.po(f" **** hostname/domain is missing in mirror url {mask_token(mirror_url)}")
        return

    if not (token := url_parts.password):
        cae.po(f" **** token missing in mirror url {mask_token(mirror_url)}")
        return

    ini_rep = None  # set to callable if any post-creation initialisations of the mirrored repo are needed
    if hostname == 'codeberg.org':
        group_project = owner_project_from_url(mirror_url)
        usr_or_org, repo_name = group_project.split("/", maxsplit=1)
        if err_msg := ensure_repo(usr_or_org, repo_name, token, main_branch=ini_pdv['MAIN_BRANCH']):
            cae.po(f" **** codeberg repository check failed: {err_msg}")
            return

    elif hostname == 'github.com':    # GitHub server does not allow to create initial/new mirror via git push
        group_project = owner_project_from_url(mirror_url)
        usr_or_org, repo_name = group_project.split("/", maxsplit=1)
        mirror_api = GithubCom()
        if not mirror_api.connect(cast(ProjectDevVars, {'repo_token': token})):
            cae.po(" **** connection to mirror host/server (github.com) failed (check os env variable $GITHUB_TOKEN).")
            return
        if not mirror_api.repo_obj(0, "", group_project):
            group_obj = mirror_api.group_obj(usr_or_org)
            if not group_obj:
                cae.po(f" **** invalid user or organization name {usr_or_org}")
                return
            group_obj.create_repo(repo_name)
            ini_rep = partial(mirror_api.init_new_repo, group_project, ini_pdv['project_title'], ini_pdv['MAIN_BRANCH'])

    # git push --prune <url+token> '+refs/heads/*:refs/heads/*' '+refs/tags/*:refs/tags/*' '+refs/notes/*:refs/notes/*'
    output = git_push(ini_pdv['project_path'], mirror_remote, "--prune",
                      *[f"+refs/{ref_group}/*:refs/{ref_group}/*" for ref_group in ('heads', 'tags', 'notes')])
    if output and output[0].startswith(EXEC_GIT_ERR_PREFIX):
        cae.po(f" **** update mirror error:{ppp(mask_token(output))}")
    else:
        if ini_rep is not None:
            ini_rep()
        cae.po(f" ==== successfully updated mirror at remote {mask_token(mirror_remote)}")


@_action(*ANY_PRJ_TYPE, flags={'MASKS': [], 'EDITABLE': False}, shortcut='upgrade')
def upgrade_requirements(ini_pdv: ProjectDevVars, **optional_flags):
    """ upgrade project requirements|dependencies, optionally as editable package.

    :param ini_pdv:             project dev vars of the project to create/update a mirror/replication for.
    :param optional_flags:      additional/optional command line arguments:

                                * ``EDITABLE``: requirements available as sister packager (under the same project parent
                                  folder) will be installed/upgraded as editable (via the -e option of `pip`).
                                * ``MASKS``: list of package name masks/pattern strings to restrict the upgraded
                                  packages. if not specified then all packages required by the project will be upgraded.
    """
    packages = ini_pdv.pdv_val('install_requires')
    pkg_masks = optional_flags['MASKS']
    editable = optional_flags['EDITABLE']

    with in_prj_dir_venv(ini_pdv['project_path']):
        upgraded = []
        for pkg_name in packages:
            if not pkg_masks or any(fnmatch(pkg_name, mask) for mask in pkg_masks):
                pip_args = ["--upgrade"]
                if editable and os_path_isdir(pgk_path := os_path_join("..", pkg_name)):
                    pip_args.append("--editable")
                    pip_args.append(pgk_path)
                else:
                    pip_args.append(pkg_name)
                sh_exit_if_exec_err(91, PIP_INSTALL_CMD, extra_args=pip_args, exit_msg="upgrade_requirements failed")
                upgraded.append(pip_args[-1])

    mask_msg = f" matching one of {pkg_masks}" if pkg_masks else ""
    cae.po(f" ==== upgraded {len(upgraded)} packages{mask_msg}: {' '.join(upgraded)}")


# ----------------------- main ----------------------------------------------------------------------------------------


def init_main():
    """ initialize main app instance. """
    global cae          # pylint: disable=global-statement
    # because ae.core determines the app version with stack_var('__version__') it doesn't find it, alternatively to pass
    # it via the app_version kwarg to ConsoleApp() the next line could be uncommented:
    # __version__ = module_attr('aedev.project_manager', '__version__'))
    cae = ConsoleApp(app_name="pjm", app_version=module_attr('aedev.project_manager', '__version__'),
                     debug_level=DEBUG_LEVEL_DISABLED)  # DEBUG_LEVEL_VERBOSE is now default in ae.core/ae.console

    cae.add_argument('action', help="action to execute (run `pjm -v show_actions` to display all available actions)")
    cae.add_argument('arguments',
                     help="additional arguments and optional flags, depending on specified action, e.g. all children"
                          " actions expecting either a list of package/portion names or an expression using one of the"
                          " preset children sets like all|editable|modified|develop|filterBranch|filterExpression",
                     nargs='*')
    cae.add_option('branch', "name of the branch or version-tag to checkout/filter-/work-on", "")
    cae.add_option('delay', "seconds to pause, e.g. between sub-actions of a children-bulk-action", 12.3, short_opt='w')
    cae.add_option('docs_domain', f"documentation domain (default={PDV_docs_domain})", None, short_opt=UNSET)
    cae.add_option('filterExpression', "Python expression evaluated against each children project, to be used as"
                                       " 'filterExpression' children-set-expression argument", "", short_opt='F')
    cae.add_option('filterBranch', "branch name matching the children current branch, to be used as"
                                   " 'filterBranch' children-set-expression argument", "", short_opt='B')
    cae.add_option('git_log', "enables git command logging for clone_project|fork_project actions", UNSET,
                   short_opt=UNSET)
    cae.add_option('more_verbose', "enables a more verbose console output", UNSET, short_opt='v')  # != cae.verbose
    cae.add_option('namespace_name', "namespace name of a new namespace root or portion (module/package) project", "")
    cae.add_option('project_name', "project package or portion name", "", short_opt='P')
    cae.add_option('project_path', "project root directory (default=current working directory)", "")
    cae.add_option('repo_domain', f"git hosting service domain (default={PDV_repo_domain})", None, short_opt='d')
    cae.add_option('repo_group', "upstream user|group name at the repository hosting service", None, short_opt='g')
    cae.add_option('repo_token', "user credential access token of the git hosting service", None, short_opt='t')
    cae.add_option('repo_user', "user account name at the repository hosting service", None, short_opt='u')
    cae.add_option('versionIncrementPart', "project version part to increment (0=disable, 1...3=mayor...patch)", 3,
                   short_opt='i', choices=range(4))
    cae.add_option('web_domain', "web app deployment platform (default=pythonanywhere.com)", None, short_opt=UNSET)
    cae.add_option('web_token', "user credential token at the used app deployment platform", None, short_opt=UNSET)
    cae.add_option('web_user', "user name at the used web app deployment platform", None, short_opt=UNSET)
    for template_pkg in ["namespace portion's root project"] + TPL_IMPORT_NAMES:
        tpl_pkg_suf = f" of {template_pkg} template package"                            # pylint: disable=invalid-name
        cae.add_option(template_path_option(template_pkg), "local path" + tpl_pkg_suf, "", short_opt=UNSET)
        cae.add_option(template_version_option(template_pkg), "branch/version-tag" + tpl_pkg_suf, "", short_opt=UNSET)

    return cae


def prepare_and_run_main():                                                                # pragma: no cover
    """ prepare and run app """
    ini_pdv, act_name, act_args, act_flags = _init_act_exec_args()  # init globals, check action, compile args
    host_api = ini_pdv.pdv_val('host_api')                          # determine optional host API client instance
    action_callable = _act_callable(host_api, act_name)             # determine action function|method

    if get_app_option(ini_pdv, 'help'):
        cae.po()
        cae.show_help()
        if act_specs := _act_specs(act_name):
            cae.po()
            cae.po(f"found {len(act_specs)} {act_name} actions:" if len(act_specs) > 1 else "action details:")
            for spec in act_specs:
                _act_help_print(spec, indent=2)                     # show help for action
    else:
        action_callable(ini_pdv, *act_args, **act_flags)            # execute action

    if not cae.verbose:                                             # if not in verbose debug mode then
        temp_context_cleanup()                                      # cleanup default context and git clone context
        temp_context_cleanup(GIT_CLONE_CACHE_CONTEXT)

    if left_forces := cae.get_option('force'):
        cae.po(f"    ¡ ignoring {left_forces} unused --force options")


def main():                                                         # pragma: no cover
    """ main app script """
    try:
        init_main()                 # initialize ConsoleApp instance with arguments
        cae.run_app()               # parse command line arguments
        prepare_and_run_main()
    except Exception as main_ex:                                    # pylint: disable=broad-exception-caught
        debug_info = f":{os.linesep}{format_exc()}" if debug_or_verbose() else ""
        cae.shutdown(99, error_message=f"unexpected exception {main_ex} raised{debug_info}")


if __name__ == '__main__':                                                                  # pragma: no cover
    main()
