"""
templates for managed files of Python projects
==============================================


"""
from difflib import context_diff, diff_bytes, ndiff, unified_diff
from functools import partial
from typing import Any, Union, cast

from ae.base import (                                                                                   # type: ignore
    TEMPLATES_FOLDER,
    in_wd, norm_name, norm_path, os_path_isdir, os_path_isfile, os_path_join, os_path_relpath, pep8_format)
from ae.console import ConsoleApp                                                                       # type: ignore
from ae.managed_files import (                                                                          # type: ignore
    DEFAULT_PATH_PREFIXES_PARSERS, DEPLOY_LOCK_EXT,
    ManagedFile, TemplateMngr, TemplateFiles)
from ae.paths import path_items                                                                         # type: ignore
from ae.shell import debug_or_verbose                                                                   # type: ignore
from aedev.base import (                                                                                # type: ignore
    ANY_PRJ_TYPE, NO_PRJ, PROJECT_VERSION_SEP, ROOT_PRJ, CachedTemplates, TemplateProjectsType, TemplateProjectType,
    get_pypi_versions, project_name_version)
from aedev.commands import (                                                                            # type: ignore
    EXEC_GIT_ERR_PREFIX, GIT_VERSION_TAG_PREFIX,
    git_clone, sh_exit_if_git_err)
from aedev.project_vars import ProjectDevVars, frozen_req_file_path                                     # type: ignore

from aedev.project_manager.utils import PPF, get_app_option, ppp


# global helpers  -----------------------------------------------------------------------------------------------------
CACHED_TPL_PROJECTS: CachedTemplates = {}
""" map to temporarily cache registered/cloned template projects. not used directly by this module, but declared
globally here to be used as argument value for :paramref:`project_templates.cached_templates` and
:paramref:`register_template.cached_templates`.
"""
MOVE_TPL_TO_PKG_PATH_NAME_PREFIX = 'de_mtp_'
""" template path prefix, to move the templates (instead of the project path, underneath of it) to the package path. """
SKIP_IF_PORTION_PREFIX = 'de_sfp_'
""" template file/path prefix to skip deployment of template to namespace portion. will be removed from destination
file name by :func:`deploy_template`, but the check if the destination project is a namespace portion has to be done
externally, by not calling the :func:`deploy_template` function for templates with this prefix.
"""
SKIP_PRJ_TYPE_PREFIX = 'de_spt_'
""" file name prefix followed by a project type id arg (see *_PRJ constants). file creation/update from template will be
skipped if it the project type id in the template file name matches the destination project type.
"""

TPL_IMPORT_NAME_PREFIX = 'aedev.'                       #: package/import name prefix of project type template packages
TPL_IMPORT_NAME_SUFFIX = '_tpls'                        #: package/import name suffix of project type template packages

TPL_PATH_OPTION_SUFFIX = '_project_path'                #: option name suffix to specify template project root folder
TPL_VERSION_OPTION_SUFFIX = '_project_version'          #: option name suffix to specify template package version

TPL_IMPORT_NAMES = ([TPL_IMPORT_NAME_PREFIX + norm_name(_) + TPL_IMPORT_NAME_SUFFIX for _ in ANY_PRJ_TYPE] +
                    [TPL_IMPORT_NAME_PREFIX + 'project' + TPL_IMPORT_NAME_SUFFIX])
""" import names of the generic project-type-related (aedev) template projects """


# pylint: disable=too-many-locals,too-many-branches,too-many-statements
def check_templates(cae: ConsoleApp, pdv: ProjectDevVars, fail_on_outdated: bool = False) -> TemplateMngr | None:
    """ check the project files that are outdated or missing from the registered namespace/project templates.

    :param cae:                 ConsoleApp instance.
    :param pdv:                 project env/dev variables dict of the destination project to patch/refresh,
                                providing values for (1) f-string template replacements, and (2) to control the template
                                registering, patching, and deployment.
    :param fail_on_outdated:    pass True to quit app if there are missing/outdated managed files (skip-able with -f).
    :return:                    :class:`TemplateMngr` instance with the current state of the project files generated
                                and synced from templates. e.g. to retrieve a set of the destination project file paths
                                that would be created/updated use set(<this return value>.deploy_files.keys()).

    .. note:: ensure the CWD is on the destination project root folder (missing/outdated_files paths are relative).
    """
    cae.chk(41, not (errors := pdv.errors()), f"project dev var {errors=}")  # if pdv['AUTHOR']

    project_type = pdv['project_type']
    if project_type == NO_PRJ:
        return None

    namespace_name = pdv['namespace_name']
    project_path = pdv['project_path']
    pdv['pypi_versions'] = get_pypi_versions(pdv['pip_name'], pypi_test=pdv['parent_folder'] == 'TsT')

    dev_requires = pdv.pdv_val('dev_requires')
    dev_req_path = os_path_join(project_path, pdv['REQ_DEV_FILE_NAME'])
    add_dev_req = (not dev_requires and not os_path_isfile(dev_req_path)
                   and not os_path_isfile(dev_req_path + DEPLOY_LOCK_EXT))
    if 'project_templates' not in pdv:
        project_tpls = pdv['project_templates'] = project_templates(
            project_type, namespace_name, _get_app_tpl_options(cae, pdv), CACHED_TPL_PROJECTS,
            dev_requires if add_dev_req else tuple(dev_requires), version_tag_prefix=pdv['VERSION_TAG_PREFIX'])
        for tpl_prj in project_tpls:
            cae.dpo(tpl_prj['register_message'])
    else:
        project_tpls = pdv.pdv_val('project_templates')

    verbose = debug_or_verbose()
    if verbose:
        if project_tpls:
            msg = f"  --- {pdv['project_title']} uses {len(project_tpls)} template project(s): "
            if cae.debug:
                cae.po(msg)
                cae.po(f"      {PPF(project_tpls)}")
            else:
                cae.po(msg + " ".join(_['import_name'] + PROJECT_VERSION_SEP + _['version'] for _ in project_tpls))
        cae.vpo(f"   -- all {len(CACHED_TPL_PROJECTS)} registered/cached template projects:")
        cae.vpo(f"      {PPF(CACHED_TPL_PROJECTS)}")
        if add_dev_req:
            cae.vpo(f"   -- added {len(dev_requires)} template projects to {dev_req_path}: {PPF(dev_requires)}")
        else:
            drt = [_ for _ in dev_requires
                   if _.startswith(norm_name(TPL_IMPORT_NAME_PREFIX)) and _.find(TPL_IMPORT_NAME_SUFFIX) != -1
                   or _.startswith(namespace_name + '_' + namespace_name)]
            cae.vpo(f"   -- {dev_req_path} activating {len(drt)} template projects: {PPF(drt)}")

    get_files = partial(path_items, selector=os_path_isfile)
    tpl_files: TemplateFiles = []  # templates projects&versions, source file paths and relative sub-paths
    for tpl_prj in project_tpls:
        tpl_path = tpl_prj['tpl_path']
        patcher = f"by the project {tpl_prj['import_name']} {pdv['VERSION_TAG_PREFIX']}{tpl_prj['version']}"
        for tpl_file_path in get_files(os_path_join(tpl_path, "**/.*")) + get_files(os_path_join(tpl_path, "**/*")):
            tpl_files.append((patcher, tpl_file_path, os_path_relpath(tpl_file_path, tpl_path)))

    tpl_vars = pdv.copy()
    tpl_vars['frozen_req_file_path'] = frozen_req_file_path
    tpl_vars['setup_kwargs_literal'] = setup_kwargs_literal
    tpl_vars['_add_base_globals'] = ""    # e.g. norm_name() is needed by dev_requirements.txt templates

    man = TemplateMngr(tpl_files, PATH_PREFIXES_PARSERS, tpl_vars)

    tpls: list[TemplateProjectType] = pdv.pdv_val('project_templates')
    tpl_cnt = len(tpls)
    cae.dpo(f"   -- checked {tpl_cnt} of {len(CACHED_TPL_PROJECTS)} registered/cached template projects: "
            + (PPF(tpls) if cae.verbose else " ".join(_['import_name'] + " v" + _['version'] for _ in tpls)))

    missing = man.missing_files
    outdated = man.outdated_files
    if missing or outdated:
        if missing:
            cae.po(f"   -- {len(missing)} managed files missing: "
                   + (PPF(missing) if cae.debug else " ".join(missing)))
        if outdated:
            cae.po(f"   -- {len(outdated)} managed files outdated: " +
                   (PPF(outdated) if cae.debug else " ".join(fn for fn, *_ in outdated)))
        for file_name, new_content, old_content in outdated:
            cae.po(f"    - {file_name}  ------------")
            if isinstance(new_content, bytes) or isinstance(old_content, bytes):    # old_content check for mypy
                dif = [str(_) for _ in diff_bytes(unified_diff, [old_content], [new_content])]
            else:
                new_lines = new_content.splitlines(keepends=True)
                old_lines = old_content.splitlines(keepends=True)
                if verbose:
                    if cae.verbose:
                        dif = list(ndiff(old_lines, new_lines))
                    else:
                        dif = list(context_diff(old_lines, new_lines))
                else:
                    if cae.debug:
                        dif = list(unified_diff(old_lines, new_lines, n=cae.debug_level))
                    else:
                        dif = [line for line in ndiff(old_lines, new_lines) if line[0:1].strip()]
            cae.po("      " + "      ".join(dif), end="")

        cae.po()
        cae.chk(44, not fail_on_outdated, f"template check failed: {len(missing)=} {len(outdated)=}"
                                          f"; update managed files via the actions 'refresh' or 'renew'")

    elif checked := man.checked_files:
        cae.po(f"  === {len(checked)} managed files from {tpl_cnt} template projects are up-to-date"
               + (": " + (ppp(checked) if cae.verbose else " ".join(checked))
                  if verbose else ""))

    elif verbose:
        cae.po(f"   == all {len(man.managed_files)} managed files of {tpl_cnt} associated template projects skipped!")

    if cae.debug:
        cae.po(f"   == template sync log of {len(man.managed_files)} managed files from {tpl_cnt} templates projects")
        for log_line in man.log_lines(verbose=cae.verbose):
            cae.po(log_line)

    return man


def clone_template_project(import_name: str, version_tag: str, repo_root: str = "") -> str:
    """ clone template package project from gitlab.com

    :param import_name:         template package import name.
    :param version_tag:         version tag of the template package to clone.
    :param repo_root:           optional remote root URL to clone the template package from. if not specified then it
                                compiles from the aedev.project_vars-defaults for protocol/domain/group-suffix and
                                the namespace from the :paramref:`~clone_template_project.import_name` argument.
    :return:                    path to the templates folder within the template package project
                                or an empty string if an error occurred..
    """
    namespace_name, portion_name = import_name.split('.')
    if not repo_root:
        # repo_root=f"{PDV_REPO_HOST_PROTOCOL}{PDV_repo_domain}/{namespace_name}{PDV_REPO_GROUP_SUFFIX}"
        repo_root = f"https://gitlab.com/{namespace_name}-group"

    # partial clone tpl-prj into tmp dir, --depth 1 extra-arg is redundant if branch_or_tag/--single-branch is specified
    path = git_clone(repo_root, norm_name(import_name), "--filter=blob:none", "--sparse", branch_or_tag=version_tag)
    if path:
        sub_dir_parts = (namespace_name, portion_name, TEMPLATES_FOLDER)
        with in_wd(path):
            tpl_dir = '/'.join(sub_dir_parts)   # git sparse-checkout expects *nix-path-separator also on MsWindows
            output = sh_exit_if_git_err(445, "git sparse-checkout", extra_args=("add", tpl_dir), exit_on_err=False)
        path = "" if output and output[0].startswith(EXEC_GIT_ERR_PREFIX) else os_path_join(path, *sub_dir_parts)

    return path


def _get_app_tpl_options(cae: ConsoleApp, pdv: ProjectDevVars) -> dict[str, str]:
    req_ver = {_o: cast(str, get_app_option(pdv, _o)) for _o in cae.cfg_options
               if _o.endswith(TPL_PATH_OPTION_SUFFIX) or _o.endswith(TPL_VERSION_OPTION_SUFFIX)} \
            if 'main_app_options' in pdv else {}
    return req_ver


def path_pfx_place_into_package_path(managed_file: ManagedFile):
    """ path prefix callee for the :data:`MOVE_TPL_TO_PKG_PATH_NAME_PREFIX` prefix.

    :param managed_file:        ManagedFile instance.
    """
    ctx_vars = managed_file.manager.context_vars
    pkg_path = os_path_relpath(ctx_vars['package_path'], ctx_vars['project_path'])
    if pkg_path != '.':
        managed_file.extend_dst_file_path(pkg_path)


def path_pfx_skip_if_project_type(managed_file: ManagedFile, project_type: str):
    """ path prefix callback for the :data:`SKIP_PRJ_TYPE_PREFIX` prefix.

    :param managed_file:        ManagedFile instance.
    :param project_type:        project type prefix arg.
    """
    if project_type == managed_file.manager.context_vars['project_type']:
        managed_file.skip(f"destination-project-type ({project_type=})")


def path_pfx_skip_if_portion(managed_file: ManagedFile):
    """ path prefix callee for the :data:`SKIP_IF_PORTION_PREFIX` prefix.

    :param managed_file:        ManagedFile instance.
    """
    ctx_vars = managed_file.manager.context_vars
    if bool(ctx_vars['namespace_name']) and ctx_vars['project_type'] != ROOT_PRJ:
        managed_file.skip("destination-project-is-namespace-portion-skip")


PATH_PREFIXES_PARSERS = dict(DEFAULT_PATH_PREFIXES_PARSERS, **{
    MOVE_TPL_TO_PKG_PATH_NAME_PREFIX: (0, path_pfx_place_into_package_path),
    SKIP_PRJ_TYPE_PREFIX: (1, path_pfx_skip_if_project_type),
    SKIP_IF_PORTION_PREFIX: (0, path_pfx_skip_if_portion),
})


# pylint: disable-next=too-many-arguments,too-many-positional-arguments
def project_templates(project_type: str, namespace_name: str,
                      requested_options: dict[str, str],
                      cached_templates: CachedTemplates,
                      dev_requires: Union[list[str], tuple[str, ...]],
                      version_tag_prefix: str = GIT_VERSION_TAG_PREFIX
                      ) -> TemplateProjectsType:
    """ get template packages (optionally clone and register) of a project with the specified project type&namespace.

    :param project_type:        type of the project (declared as *_PRJ constants in :mod:`aedev.base`).
    :param namespace_name:      name of the namespace if the project is a portion, else an empty string.
    :param requested_options:   dict with explicitly requested template packages via their version or their local path.
                                if not specified for a template package then the version specified by the
                                :paramref:`project_templates.dev_requires` will be used. the keys of this dict are
                                created with the helper functions :func:`template_path_option` or
                                :func:`template_version_option`. the values are accordingly either local file paths
                                or version strings of the template packages to use/register.
    :param cached_templates:    map of the cached/registered template projects (e.g. :data:`CACHED_TPL_PROJECTS`).
                                unregistered templates packages needed by the specified project type/name-space will be
                                automatically added to this register/map.
    :param dev_requires:        list/tuple of packages required by the project (from the projects dev_requirements.txt
                                file) which can contain template packages with their version number. if the versions of
                                the needed template packages are not specified, then the latest versions will be used.
                                when specified as list type and the registered template package version got cloned then
                                it will be appended as new list entry.
    :param version_tag_prefix:  version tag prefix.
    :return:                    list of the template packages needed by the specified project type/namespace.
    """
    template_projects: list[TemplateProjectType] = []
    reg_args = requested_options, cached_templates, dev_requires, template_projects, version_tag_prefix

    if namespace_name:
        register_template(namespace_name + '.' + namespace_name, *reg_args)
    register_template(TPL_IMPORT_NAME_PREFIX + norm_name(project_type) + TPL_IMPORT_NAME_SUFFIX, *reg_args)
    register_template(TPL_IMPORT_NAME_PREFIX + 'project' + TPL_IMPORT_NAME_SUFFIX, *reg_args)

    return template_projects


# pylint: disable-next=too-many-arguments,too-many-positional-arguments,too-many-locals
def register_template(import_name: str, requested_options: dict[str, str], cached_templates: CachedTemplates,
                      dev_requires: Union[list[str], tuple[str, ...]], template_packages: TemplateProjectsType,
                      version_tag_prefix: str = GIT_VERSION_TAG_PREFIX, clone_url: str = ""):
    """ add/update the template register and the template packages list for the specified template package and version.

    :param import_name:         import name of the template package.
    :param requested_options:   see description of the parameter :paramref:`project_template.requested_options`.
    :param cached_templates:    see description of the parameter :paramref:`project_template.cached_templates`.
    :param dev_requires:        see description of the parameter :paramref:`project_template.dev_requires`.
    :param template_packages:   list of template packages, to be extended with the specified template package/version.
    :param version_tag_prefix:  version tag prefix.
    :param clone_url:           optional URL to clone a template package from (see :func:`clone_template_project`).
    :raises AssertionError:     if both, the local path and the version option is specified.
    """
    prj_path = requested_options.get(template_path_option(import_name), "")
    prj_version = requested_options.get(template_version_option(import_name), '')

    if prj_path:
        assert not prj_version, f"specify template {import_name} either by {prj_path=} or by {prj_version=} not by both"
        prj_version = 'local'
        templates_path = norm_path(os_path_join(prj_path, *import_name.split('.'), TEMPLATES_FOLDER))
        assert os_path_isdir(templates_path), f"{import_name} templates path {templates_path} does not exist"
    else:
        templates_path = ""
        project_name = norm_name(import_name)
        if not prj_version:
            _dev_req_pkg, dev_req_ver = project_name_version(project_name, dev_requires)
            if dev_req_ver:
                prj_version = dev_req_ver
            else:
                reg_pkg, prj_version = project_name_version(project_name, list(cached_templates.keys()))
                if not reg_pkg:
                    prj_version = get_pypi_versions(project_name)[-1]  # no 'aetst' tpl projects; they're all in 'aedev'

        if isinstance(dev_requires, list) and prj_version:
            if (dev_req_line := project_name + PROJECT_VERSION_SEP + prj_version) not in dev_requires:
                dev_requires.append(dev_req_line)

    key = import_name + PROJECT_VERSION_SEP + prj_version
    if key not in cached_templates:
        if prj_version not in ('', 'local'):
            templates_path = clone_template_project(import_name, version_tag_prefix + prj_version, repo_root=clone_url)
        cached_templates[key] = {
            'import_name': import_name, 'tpl_path': templates_path, 'version': prj_version,
            'register_message':
                f"    - {import_name=} package {prj_version=} in {templates_path=} registered as template id/{key=}"
                if templates_path and prj_version else
                f"    # template project {import_name=} not found/registered ({prj_version=} {prj_path=})"}

    if prj_version:
        template_packages.append(cached_templates[key])


def setup_kwargs_literal(setup_kwargs: dict[str, Any]) -> str:
    """ literal string of the setuptools.setup() kwargs dict, to be used by the setup.py template (aedev.project_tpls).

    :param setup_kwargs:        kwargs passed to call of _func:`setuptools.setup` in setup.py.
                                in order to prevent errors if the template-generated file README.md get created after
                                setup.py and to have a nicer code formatting in the resulting setup.py file, the value
                                of the `long_description` item will be replaced by a dynamic-loading expression.
    :return:                    literal of specified setup kwargs formatted for column 1.

    .. note:: the setup.py template has to include/provide the statement: import pathlib.
    """
    sep = "\n"      # not using os.linesep to prevent formatting discrepancies on different operating systems.
    pre = sep + " " * 4
    ret = "{"

    for key in sorted(setup_kwargs.keys()):
        ret += pre + repr(key) + ": "
        if key == 'long_description':  # replace preloaded content of README with dynamic file content load expression
            ret += "(pathlib.Path(__file__).parent / 'README.md').read_text(encoding='utf-8')"
        else:
            ret += pep8_format(setup_kwargs[key], indent_level=1)  # pformat(setup_kwargs[key], indent=8, width=120)
        ret += ","

    return ret + sep + "}"


def _template_options_prefix(import_name: str) -> str:
    option_name = import_name.split('.')[-1]
    if option_name.endswith(TPL_IMPORT_NAME_SUFFIX):    # if it is a project type template (aedev.<project type>_tpls)
        return norm_name(option_name)                   # then use the template project portion name as option prefix
    return 'portions_namespace_root'                     # for the portion's namespace root use hardcoded option name


def template_path_option(import_name: str) -> str:
    """ unique key of a template package import name usable for command line options and to specify a template path.

    :param import_name:         template package import name.
    :return:                    template package version option key/name.
    """
    return _template_options_prefix(import_name) + TPL_PATH_OPTION_SUFFIX


def template_version_option(import_name: str) -> str:
    """ unique key of a template package import name usable for command line options and to specify a template version.

    :param import_name:         template package import name.
    :return:                    template package path option key/name.
    """
    return _template_options_prefix(import_name) + TPL_VERSION_OPTION_SUFFIX
