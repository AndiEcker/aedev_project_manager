"""
templates for outsourced files of Python projects
=================================================


"""
from pprint import pformat
from typing import Union, Any

from ae.base import TEMPLATES_FOLDER, in_wd, norm_name, norm_path, os_path_isdir, os_path_join  # type: ignore
from aedev.base import (                                                                        # type: ignore
    PROJECT_VERSION_SEP, CachedTemplates, TemplateProjectsType, TemplateProjectType,
    get_pypi_versions, project_name_version)
from aedev.commands import (                                                                    # type: ignore
    EXEC_GIT_ERR_PREFIX, GIT_VERSION_TAG_PREFIX,
    git_clone, sh_exit_if_git_err)


__version__ = '0.3.1'


# global helpers  -----------------------------------------------------------------------------------------------------
CACHED_TPL_PROJECTS: CachedTemplates = {}
""" map to temporarily cache registered/cloned template projects. not used directly by this module, but declared
globally here to be used as argument value for :paramref:`project_templates.cached_templates` and
:paramref:`register_template.cached_templates`.
"""
MOVE_TPL_TO_PKG_PATH_NAME_PREFIX = 'de_mtp_'
""" template file/folder name prefix, to move the templates to the package path (instead of the project path);
has to be specified after :data:`SKIP_IF_PORTION_DST_NAME_PREFIX` (if both prefixes are needed). declared in this
portion for completeness, but not directly used. for external use: caller of :func:`deploy_template` has to remove this
prefix from destination file name (adapting the :paramref:`destination path argument <deploy_template.dst_path`).
"""

TPL_IMPORT_NAME_PREFIX = 'aedev.'                       #: package/import name prefix of project type template packages
TPL_IMPORT_NAME_SUFFIX = '_tpls'                        #: package/import name suffix of project type template packages

TPL_PATH_OPTION_SUFFIX = '_project_path'                #: option name suffix to specify template project root folder
TPL_VERSION_OPTION_SUFFIX = '_project_version'          #: option name suffix to specify template package version


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
    """ literal string of the setuptools.setup() kwargs dict used in setup.py.

    :param setup_kwargs:        kwargs passed to call of _func:`setuptools.setup` in setup.py.
    :return:                    literal of specified setup kwargs formatted for column 1.
    """
    ret = "{"
    pre = "\n" + " " * 4
    for key in sorted(setup_kwargs.keys()):
        ret += pre + repr(key) + ": " + pformat(setup_kwargs[key], indent=8, width=120, compact=True) + ","
    return ret + "\n}"


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
