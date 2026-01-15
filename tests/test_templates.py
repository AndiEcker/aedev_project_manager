""" project manager templates unit tests """
import os
import textwrap

import pytest

from aedev.project_manager.templates import PATH_PREFIXES_PARSERS
from tests.conftest import skip_gitlab_ci

from ae.base import (
    DEF_PROJECT_PARENT_FOLDER, PY_EXT, PY_INIT, TEMPLATES_FOLDER,
    in_wd, norm_name, norm_path, os_path_basename, os_path_dirname, os_path_isdir, os_path_isfile, os_path_join,
    read_file, write_file)
from ae.core import main_app_instance, temp_context_cleanup, temp_context_folders
from ae.managed_files import (
    PATH_PREFIXES_ARGS_SEP, REFRESHABLE_TEMPLATE_PATH_PFX, REFRESHABLE_TEMPLATE_MARKER,
    F_STRINGS_PATH_PFX, TEMPLATE_PLACEHOLDER_ID_PREFIX, TEMPLATE_PLACEHOLDER_ID_SUFFIX,
    TEMPLATE_PLACEHOLDER_ARGS_SUFFIX, TEMPLATE_INCLUDE_FILE_PLACEHOLDER_ID,
    deploy_template, patch_string)
from aedev.base import (
    PROJECT_VERSION_SEP, MODULE_PRJ, PACKAGE_PRJ, PARENT_PRJ, ROOT_PRJ, project_name_version)
from aedev.commands import GIT_CLONE_CACHE_CONTEXT, GIT_VERSION_TAG_PREFIX
from aedev.project_vars import PDV_REQ_DEV_FILE_NAME, ProjectDevVars

# noinspection PyProtectedMember
from aedev.project_manager.__main__ import _renew_prj_dir

from constants_and_fixtures import app_pjm, changed_repo_path, empty_repo_path, mocked_app_options, module_repo_path

from aedev.project_manager.templates import (
    CACHED_TPL_PROJECTS, SKIP_IF_PORTION_PREFIX, SKIP_PRJ_TYPE_PREFIX,
    TPL_IMPORT_NAME_PREFIX, TPL_IMPORT_NAME_SUFFIX, TPL_PATH_OPTION_SUFFIX, TPL_VERSION_OPTION_SUFFIX,
    check_templates, clone_template_project, project_templates, register_template,
    setup_kwargs_literal, template_path_option, template_version_option)


def teardown_module():
    """ pytest test module teardown to clear registered template projects and to check if main app gets used. """
    print(f"##### {os_path_basename(__file__)} teardown_module BEG - {CACHED_TPL_PROJECTS=} {main_app_instance()=}")

    CACHED_TPL_PROJECTS.clear()         # remove registered template projects from project_manager.templates.py module
    temp_context_cleanup()
    temp_context_cleanup(GIT_CLONE_CACHE_CONTEXT)

    print(f"##### {os_path_basename(__file__)} teardown_module END - {CACHED_TPL_PROJECTS=} {main_app_instance()=}")


@pytest.fixture
def cleanup_git_clone_cache():
    assert not temp_context_folders(GIT_CLONE_CACHE_CONTEXT)
    yield
    temp_context_cleanup(GIT_CLONE_CACHE_CONTEXT)


def test_declaration_of_template_vars(cleanup_git_clone_cache):
    assert isinstance(REFRESHABLE_TEMPLATE_MARKER, str)
    assert isinstance(REFRESHABLE_TEMPLATE_PATH_PFX, str)
    assert isinstance(F_STRINGS_PATH_PFX, str)
    assert isinstance(TEMPLATE_PLACEHOLDER_ID_PREFIX, str)
    assert isinstance(TEMPLATE_PLACEHOLDER_ID_SUFFIX, str)
    assert isinstance(TEMPLATE_PLACEHOLDER_ARGS_SUFFIX, str)
    assert isinstance(TEMPLATE_INCLUDE_FILE_PLACEHOLDER_ID, str)


class TestHelpers:
    def test_app_options_namespace_module(self, cons_app, tmp_path):
        nsn = 'abc'
        parent_dir = os_path_join(str(tmp_path), DEF_PROJECT_PARENT_FOLDER)
        portion_name = 'tst_ns_mod'
        project_path = os_path_join(parent_dir, nsn + '_' + portion_name)
        module_path = os_path_join(project_path, nsn, portion_name + PY_EXT)
        app_options = {'repo_group': "tst_grp",
                       template_version_option(nsn + '.' + nsn): ""}

        os.makedirs(os_path_dirname(module_path))
        write_file(module_path, f"mod_content = ''{os.linesep}__version__ = '3.3.3'{os.linesep}")

        pdv = ProjectDevVars(project_path=project_path, **app_options)

        assert pdv['namespace_name'] == nsn
        assert pdv['project_name'] == nsn + '_' + portion_name
        assert pdv['package_path'] == os_path_join(norm_path(project_path), nsn, portion_name)
        assert pdv['project_path'] == norm_path(project_path)
        assert pdv['project_type'] == MODULE_PRJ
        assert pdv['repo_group'] == app_options['repo_group']
        assert pdv['version_file'] == norm_path(module_path)

        pdv = ProjectDevVars(project_path=parent_dir, **app_options)

        assert pdv['namespace_name'] == ""
        assert pdv['project_name'] == os_path_basename(parent_dir)
        assert pdv['project_path'] == norm_path(parent_dir)
        assert pdv['project_type'] == PARENT_PRJ
        assert pdv['repo_group'] == app_options['repo_group']
        assert f"{nsn}_{portion_name}" in pdv.pdv_val('children_project_vars')
        assert 'portions_import_names' not in pdv

    def test_app_options_namespace_package(self, cons_app, tmp_path):
        nsn = 'efg'
        parent_dir = os_path_join(str(tmp_path), DEF_PROJECT_PARENT_FOLDER)
        portion_name = 'tst_ns_pkg'
        project_path = os_path_join(parent_dir, nsn + '_' + portion_name)
        package_path = os_path_join(project_path, nsn, portion_name)
        app_options = {'repo_group': "tst_grp",
                       template_version_option(nsn + '.' + nsn): ""}

        os.makedirs(package_path)
        write_file(os_path_join(package_path, PY_INIT),
                   f"pkg_ini_content = ''{os.linesep}__version__ = '6.3.6'{os.linesep}")

        pdv = ProjectDevVars(project_path=project_path, **app_options)

        assert pdv['namespace_name'] == nsn
        assert pdv['project_name'] == nsn + '_' + portion_name
        assert pdv['package_path'] == norm_path(package_path)
        assert pdv['project_path'] == norm_path(project_path)
        assert pdv['project_type'] == PACKAGE_PRJ
        assert pdv['repo_group'] == app_options['repo_group']
        assert pdv['version_file'] == norm_path(os_path_join(package_path, PY_INIT))

        app_options['namespace_name'] = nsn

        pdv = ProjectDevVars(project_path=project_path, **app_options)

        assert pdv['namespace_name'] == nsn
        assert pdv['project_name'] == nsn + '_' + portion_name
        assert pdv['package_path'] == norm_path(package_path)
        assert pdv['project_path'] == norm_path(project_path)
        assert pdv['project_type'] == PACKAGE_PRJ
        assert pdv['repo_group'] == app_options['repo_group']
        assert pdv['version_file'] == norm_path(os_path_join(package_path, PY_INIT))

        app_options['namespace_name'] = ""

        pdv = ProjectDevVars(project_path=parent_dir, **app_options)

        assert pdv['namespace_name'] == ""
        assert pdv['project_name'] == os_path_basename(parent_dir)
        assert pdv['project_path'] == norm_path(parent_dir)
        assert pdv['project_type'] == PARENT_PRJ
        assert pdv['repo_group'] == app_options['repo_group']
        assert f"{nsn}_{portion_name}" in pdv.pdv_val('children_project_vars')
        assert 'portions_import_names' not in pdv

    def test_app_options_namespace_root(self, cons_app, tmp_path):
        nsn = 'hij'
        parent_dir = os_path_join(str(tmp_path), DEF_PROJECT_PARENT_FOLDER)
        project_path = os_path_join(parent_dir, nsn + '_' + nsn)
        package_path = os_path_join(project_path, nsn, nsn)
        app_options = {'repo_group': "tst_grp",
                       template_version_option(nsn + '.' + nsn): ""}

        os.makedirs(package_path)
        write_file(os_path_join(package_path, PY_INIT),
                   f"root_content = ''{os.linesep}__version__ = '9.9.3'{os.linesep}")

        pdv = ProjectDevVars(project_path=project_path, **app_options)

        assert pdv['namespace_name'] == nsn
        assert pdv['project_name'] == nsn + '_' + nsn
        assert pdv['package_path'] == norm_path(package_path)
        assert pdv['project_path'] == norm_path(project_path)
        assert pdv['project_type'] == ROOT_PRJ
        assert pdv['repo_group'] == app_options['repo_group']
        assert pdv['version_file'] == norm_path(os_path_join(package_path, PY_INIT))
        assert not pdv.pdv_val('children_project_vars')
        assert not pdv.pdv_val('portions_import_names')

        app_options['namespace_name'] = nsn

        pdv = ProjectDevVars(project_path=project_path, **app_options)

        assert pdv['namespace_name'] == nsn
        assert pdv['project_name'] == nsn + '_' + nsn
        assert pdv['package_path'] == norm_path(package_path)
        assert pdv['project_path'] == norm_path(project_path)
        assert pdv['project_type'] == ROOT_PRJ
        assert pdv['repo_group'] == app_options['repo_group']
        assert pdv['version_file'] == norm_path(os_path_join(package_path, PY_INIT))
        assert not pdv.pdv_val('children_project_vars')
        assert not pdv.pdv_val('portions_import_names')

        app_options['namespace_name'] = ""

        pdv = ProjectDevVars(project_path=parent_dir, **app_options)

        assert pdv['namespace_name'] == ""
        assert pdv['project_name'] == os_path_basename(parent_dir)
        assert pdv['project_path'] == norm_path(parent_dir)
        assert pdv['project_type'] == PARENT_PRJ
        assert pdv['repo_group'] == app_options['repo_group']
        assert f"{nsn}_{nsn}" in pdv.pdv_val('children_project_vars')
        assert 'portions_import_names' not in pdv

    def test_app_options_namespace_root_portions(self, cons_app, tmp_path):
        nsn = 'uvw'
        parent_dir = os_path_join(str(tmp_path), DEF_PROJECT_PARENT_FOLDER)
        root_prj_path = os_path_join(parent_dir, nsn + '_' + nsn)
        root_pkg_path = os_path_join(root_prj_path, nsn, nsn)

        project_name = 'tst_ns_pkg'
        package_prj_path = os_path_join(parent_dir, nsn + '_' + project_name)
        package_pkg_path = os_path_join(package_prj_path, nsn, project_name)
        package_extra_module_name = "extra_module_name"

        module_name = 'tst_ns_module'
        module_prj_path = os_path_join(parent_dir, nsn + '_' + module_name)
        module_path = os_path_join(module_prj_path, nsn, module_name + PY_EXT)

        app_options = {'repo_group': "tst_grp",
                       template_version_option(nsn + '.' + nsn): ""}

        os.makedirs(root_pkg_path)
        write_file(os_path_join(root_pkg_path, PY_INIT),
                   f"root_content = ''{os.linesep}__version__ = '111.33.63'{os.linesep}")
        write_file(os_path_join(root_prj_path, PDV_REQ_DEV_FILE_NAME),
                   nsn + '_' + project_name + os.linesep + nsn + '_' + module_name)

        write_file(os_path_join(package_pkg_path, PY_INIT),
                   f"pkg_content = ''{os.linesep}__version__ = '999.333.636'{os.linesep}",
                   make_dirs=True)
        write_file(os_path_join(package_pkg_path, package_extra_module_name + PY_EXT), "extra_content = ''")

        os.makedirs(os_path_dirname(module_path))
        write_file(os_path_join(module_prj_path, nsn, module_name),
                   f"mod_content = ''{os.linesep}__version__ = '6.9.699'{os.linesep}")

        pdv = ProjectDevVars(project_path=root_prj_path, **app_options)

        assert pdv['namespace_name'] == nsn
        assert pdv['project_name'] == nsn + '_' + nsn
        assert pdv['package_path'] == norm_path(root_pkg_path)
        assert pdv['project_path'] == norm_path(root_prj_path)
        assert pdv['project_type'] == ROOT_PRJ
        assert pdv['repo_group'] == app_options['repo_group']
        assert pdv['version_file'] == norm_path(os_path_join(root_pkg_path, PY_INIT))

        assert f"{nsn}_{project_name}" in pdv.pdv_val('children_project_vars')
        assert f"{nsn}_{project_name}.{package_extra_module_name}" not in pdv.pdv_val('children_project_vars')
        assert f"{nsn}_{module_name}" in pdv.pdv_val('children_project_vars')

        assert f"{nsn}.{project_name}" in pdv.pdv_val('portions_import_names')
        assert f"{nsn}.{project_name}.{package_extra_module_name}" in pdv['portions_import_names']
        assert f"{nsn}.{module_name}" in pdv.pdv_val('portions_import_names')

        app_options['namespace_name'] = nsn

        pdv = ProjectDevVars(project_path=root_prj_path, **app_options)

        assert pdv['namespace_name'] == nsn
        assert pdv['project_name'] == nsn + '_' + nsn
        assert pdv['package_path'] == os_path_join(norm_path(root_prj_path), nsn, nsn)
        assert pdv['project_path'] == norm_path(root_prj_path)
        assert pdv['project_type'] == ROOT_PRJ
        assert pdv['repo_group'] == app_options['repo_group']
        assert pdv['version_file'] == norm_path(os_path_join(root_pkg_path, PY_INIT))

        assert f"{nsn}_{project_name}" in pdv.pdv_val('children_project_vars')
        assert f"{nsn}_{project_name}.{package_extra_module_name}" not in pdv.pdv_val('children_project_vars')
        assert f"{nsn}_{module_name}" in pdv.pdv_val('children_project_vars')

        assert f"{nsn}.{project_name}" in pdv.pdv_val('portions_import_names')
        assert f"{nsn}.{project_name}.{package_extra_module_name}" in pdv.pdv_val('portions_import_names')
        assert f"{nsn}.{module_name}" in pdv.pdv_val('portions_import_names')

        app_options['namespace_name'] = ""

        pdv = ProjectDevVars(project_path=parent_dir, **app_options)

        assert pdv['namespace_name'] == ""
        assert pdv['project_name'] == os_path_basename(parent_dir)
        assert pdv['project_path'] == norm_path(parent_dir)
        assert pdv['project_type'] == PARENT_PRJ
        assert pdv['repo_group'] == app_options['repo_group']
        assert f"{nsn}_{project_name}" in pdv.pdv_val('children_project_vars')
        assert f"{nsn}_{project_name}.{package_extra_module_name}" not in pdv.pdv_val('children_project_vars')
        assert f"{nsn}_{module_name}" in pdv.pdv_val('children_project_vars')
        assert 'portions_import_names' not in pdv

    def test_check_templates_empty_folder(self, app_pjm, tmp_path):
        assert check_templates(app_pjm, ProjectDevVars(project_path=str(tmp_path))) is None

    def test_check_templates_new_module_prj(self, app_pjm, cleanup_git_clone_cache, module_repo_path):
        assert check_templates(app_pjm, ProjectDevVars(project_path=module_repo_path))

    def test_check_templates_no_prj(self, app_pjm, cleanup_git_clone_cache, empty_repo_path, changed_repo_path):
        assert not check_templates(app_pjm, ProjectDevVars(project_path=empty_repo_path))
        assert not check_templates(app_pjm, ProjectDevVars(project_path=changed_repo_path))

    def test_check_templates_test_registered(self, cleanup_git_clone_cache, cons_app, tmp_path):
        parent_dir = os_path_join(str(tmp_path), DEF_PROJECT_PARENT_FOLDER)
        namespace = "nsn"
        project_name = f"{namespace}_pkg_name"
        project_path = norm_path(os_path_join(parent_dir, project_name))
        prj_tpls = [
            {'import_name': namespace + '.' + namespace,
             'tpl_path': os_path_join(parent_dir, namespace + '_' + namespace, namespace, namespace, TEMPLATES_FOLDER),
             'version': '1.1.1',
             'register_message': "manually setup for unit testing"},
            {'import_name': TPL_IMPORT_NAME_PREFIX + 'project' + TPL_IMPORT_NAME_SUFFIX,
             'tpl_path': os_path_join(parent_dir, 'aedev_package_tpls', 'aedev', 'package_tpls', TEMPLATES_FOLDER),
             'version': '3.3.3',
             'register_message': "manually setup for unit testing"},
            {'import_name': TPL_IMPORT_NAME_PREFIX + 'project' + TPL_IMPORT_NAME_SUFFIX,
             'tpl_path': os_path_join(parent_dir, 'aedev_project_tpls', 'aedev', 'project_tpls', TEMPLATES_FOLDER),
             'version': '9.9.9',
             'register_message': "manually setup for unit testing"},
        ]
        pdv = ProjectDevVars(**{'namespace_name': namespace, 'project_path': project_path, 'project_type': PACKAGE_PRJ,
                                'project_templates': []})
        _renew_prj_dir(pdv)

        with in_wd(project_path):
            assert check_templates(cons_app, pdv) is not None

        # 2nd test with template in all template projects (namespace-root template project has the highest priority)
        deep_sub_dir = os_path_join('deeper', 'even_deeper')
        file_for_all = 'file_for_all.ext'
        tpl_file_for_all = REFRESHABLE_TEMPLATE_PATH_PFX + F_STRINGS_PATH_PFX + file_for_all
        for tpl_reg in prj_tpls:
            tpl_path = os_path_join(tpl_reg['tpl_path'], deep_sub_dir)
            write_file(os_path_join(tpl_path, tpl_file_for_all), tpl_reg['tpl_path'], make_dirs=True)
        tpl_file = os_path_join(project_path, deep_sub_dir, file_for_all)
        pdv = ProjectDevVars(**{'namespace_name': namespace, 'project_path': project_path, 'project_type': PACKAGE_PRJ,
                                'project_templates': prj_tpls})

        with in_wd(project_path):
            tmg = check_templates(cons_app, pdv)
            assert set(tmg.deploy_files.keys()) == {norm_path(tpl_file)}
            assert not os_path_isfile(tpl_file)
            tmg.deploy()
            assert os_path_isfile(tpl_file)
            content = read_file(tpl_file)
        assert prj_tpls[0]['tpl_path'] in content
        assert REFRESHABLE_TEMPLATE_MARKER in content

    def test_check_templates_file_include_content(self, app_pjm, cleanup_git_clone_cache, tmp_path):
        parent_dir = os_path_join(str(tmp_path), DEF_PROJECT_PARENT_FOLDER)
        tpl_pkg_path = norm_path(os_path_join(parent_dir, 'tst_tpls', TEMPLATES_FOLDER))
        tpl_file_name = "including_content.txt"
        tpl_file_path = os_path_join(tpl_pkg_path, REFRESHABLE_TEMPLATE_PATH_PFX + F_STRINGS_PATH_PFX + tpl_file_name)
        ver = '9.6.9999'
        prj_templates = [{'import_name': TPL_IMPORT_NAME_PREFIX + 'project' + TPL_IMPORT_NAME_SUFFIX,
                          'tpl_path': tpl_pkg_path,
                          'version': ver,
                          'register_message': "manually setup for unit testing"}]
        included_file_name = norm_path(os_path_join(parent_dir, "inc.tst.file"))
        included_file_content = "replacement string"
        project_name = f"prj_name"
        project_path = os_path_join(parent_dir, project_name)
        patched_file_name = os_path_join(project_path, tpl_file_name)
        os.makedirs(project_path)
        os.makedirs(tpl_pkg_path)

        tpl = f"{TEMPLATE_PLACEHOLDER_ID_PREFIX}{TEMPLATE_INCLUDE_FILE_PLACEHOLDER_ID}"
        tpl += f"{TEMPLATE_PLACEHOLDER_ID_SUFFIX}{included_file_name}{TEMPLATE_PLACEHOLDER_ARGS_SUFFIX}"
        write_file(tpl_file_path, tpl)
        write_file(included_file_name, included_file_content)

        with in_wd(project_path):
            tmg = check_templates(app_pjm, ProjectDevVars(project_type=MODULE_PRJ, project_templates=prj_templates))
            assert not os_path_isfile(patched_file_name)
            tmg.deploy()
            assert os_path_isfile(patched_file_name)

        assert set(tmg.deploy_files.keys()) == {norm_path(patched_file_name)}

        content = read_file(patched_file_name)
        assert included_file_content in content
        assert ver in content
        assert "TEMPLATE_PLACEHOLDER_ID_PREFIX" not in content
        assert TEMPLATE_INCLUDE_FILE_PLACEHOLDER_ID not in content
        assert "TEMPLATE_INCLUDE_FILE_PLACEHOLDER_ID" not in content
        assert TEMPLATE_PLACEHOLDER_ID_SUFFIX not in content
        assert "TEMPLATE_PLACEHOLDER_ID_SUFFIX" not in content
        assert TEMPLATE_PLACEHOLDER_ARGS_SUFFIX not in content
        assert "TEMPLATE_PLACEHOLDER_ARGS_SUFFIX" not in content

    def test_check_templates_file_include_default_with_pdv(self, app_pjm, cleanup_git_clone_cache, mocked_app_options,
                                                           monkeypatch, tmp_path):
        parent_dir = os_path_join(str(tmp_path), DEF_PROJECT_PARENT_FOLDER)
        namespace_name = "tns"
        portion_name = 'destination_portion_name'
        project_path = os_path_join(parent_dir, f'{namespace_name}_{portion_name}')
        package_path = os_path_join(project_path, namespace_name)
        patched_file = "including_content.txt"
        patched_path = os_path_join(project_path, patched_file)

        tpl_imp_name = namespace_name + '.' + namespace_name
        tpl_pkg_path = norm_path(os_path_join(
            parent_dir, norm_name(tpl_imp_name), namespace_name, namespace_name, TEMPLATES_FOLDER))
        tpl_file_path = os_path_join(tpl_pkg_path, REFRESHABLE_TEMPLATE_PATH_PFX + F_STRINGS_PATH_PFX + patched_file)

        default = "include file default string"
        version = '6.699.987'

        mocked_app_options[template_version_option(tpl_imp_name)] = version
        mocked_app_options['namespace_name'] = namespace_name    # or ""
        os.makedirs(package_path)
        write_file(os_path_join(project_path, PDV_REQ_DEV_FILE_NAME), norm_name(tpl_imp_name))
        write_file(os_path_join(package_path, portion_name + PY_EXT), "__version__ = '9.6.3'")

        os.makedirs(os_path_dirname(tpl_file_path))
        tpl = "{TEMPLATE_PLACEHOLDER_ID_PREFIX}{TEMPLATE_INCLUDE_FILE_PLACEHOLDER_ID}"
        tpl += "{TEMPLATE_PLACEHOLDER_ID_SUFFIX}"
        tpl += f"not_existing_included_file_name.ext,{default}"
        tpl += "{TEMPLATE_PLACEHOLDER_ARGS_SUFFIX}"
        write_file(tpl_file_path, tpl)

        monkeypatch.setitem(CACHED_TPL_PROJECTS, tpl_imp_name + PROJECT_VERSION_SEP + version,
                            {'import_name': tpl_imp_name, 'tpl_path': tpl_pkg_path, 'version': version,
                             'register_message': "manually setup for unit testing"})

        pdv = ProjectDevVars(project_path=project_path)

        with in_wd(project_path):
            tmg = check_templates(app_pjm, pdv)

        assert 'project_templates' in pdv
        assert not os_path_isfile(patched_path)
        assert norm_path(patched_path) in set(tmg.deploy_files.keys())

        with in_wd(project_path):
            tmg.deploy()

        assert os_path_isfile(patched_path)

        content = read_file(patched_path)
        assert default in content
        assert tpl_imp_name in content
        assert version in content
        assert "TEMPLATE_PLACEHOLDER_ID_PREFIX" not in content
        assert TEMPLATE_INCLUDE_FILE_PLACEHOLDER_ID not in content
        assert "TEMPLATE_INCLUDE_FILE_PLACEHOLDER_ID" not in content
        assert TEMPLATE_PLACEHOLDER_ID_SUFFIX not in content
        assert "TEMPLATE_PLACEHOLDER_ID_SUFFIX" not in content
        assert TEMPLATE_PLACEHOLDER_ARGS_SUFFIX not in content
        assert "TEMPLATE_PLACEHOLDER_ARGS_SUFFIX" not in content

    def test_clone_template_project(self, cleanup_git_clone_cache, cons_app):
        tpl_path = clone_template_project('aedev.project_tpls', GIT_VERSION_TAG_PREFIX + '0.3.36')
        assert tpl_path
        assert os_path_isdir(tpl_path)
        assert os_path_basename(tpl_path) == TEMPLATES_FOLDER

    def test_clone_template_project_for_apps(self, cleanup_git_clone_cache, cons_app):
        tpl_path = clone_template_project('aedev.app_tpls', GIT_VERSION_TAG_PREFIX + '0.3.16')
        assert tpl_path
        assert os_path_isdir(tpl_path)
        assert os_path_basename(tpl_path) == TEMPLATES_FOLDER

    def test_deploy_template_sfp_path_pfx_remove_and_spt_in_sub_dir(self, cleanup_git_clone_cache, tmp_path):
        parent_dir = os_path_join(str(tmp_path), DEF_PROJECT_PARENT_FOLDER)
        src_dir = os_path_join(parent_dir, 'tpl_src_prj_dir')
        tpl_dir = os_path_join(src_dir, TEMPLATES_FOLDER)
        sub_dir_folder = 'sub_dir'
        tpl_sub_dir = os_path_join(tpl_dir, sub_dir_folder)
        file_name = "template_file_name.xyz"

        src_file = os_path_join(tpl_sub_dir, file_name)
        content = "template file content"
        write_file(src_file, content, make_dirs=True)

        dst_dir = os_path_join(parent_dir, 'dst')
        new_pdv = {'namespace_name': "", 'project_path': dst_dir, 'project_type': ROOT_PRJ}
        os.makedirs(dst_dir)
        prefixes = SKIP_IF_PORTION_PREFIX + SKIP_PRJ_TYPE_PREFIX + ROOT_PRJ + PATH_PREFIXES_ARGS_SEP
        dst_path = os_path_join(sub_dir_folder, prefixes + file_name)

        with in_wd(dst_dir):
            dst_file_path = deploy_template(src_file, dst_path=dst_path, patcher="tst_patcher",
                                            prefixes_parsers=PATH_PREFIXES_PARSERS, tpl_vars=new_pdv)

        assert dst_file_path == ""        # skipped deploy

        new_pdv['project_type'] = MODULE_PRJ

        with in_wd(dst_dir):
            dst_file_path = deploy_template(src_file, dst_path=dst_path, patcher="tst_patcher",
                                            prefixes_parsers=PATH_PREFIXES_PARSERS, tpl_vars=new_pdv)

        assert dst_file_path            # not skipped deploy
        dst_file = os_path_join(dst_dir, sub_dir_folder, file_name)
        assert os_path_isfile(dst_file)
        assert norm_path(dst_file) == norm_path(dst_file_path)
        assert read_file(dst_file) == content

    def test_patch_string_setup_template(self):
        setup_tpl = textwrap.dedent('''\
        """ setup of {project_desc}. """
        # ReplaceWith#({'import sys' if bool_var else ''})#
        # ReplaceWith#({'print(f"SetUp {__name__=} {sys.executable=} {sys.argv=} {sys.path=}")' if bool_var else ''})#
        # ReplaceWith#(setup_kwargs = {setup_kwargs_literal(setup_kwargs)})#
        # ReplaceWith#(setuptools.setup(**setup_kwargs))#
        ''')

        glo_vars = {'project_desc': 'ProjectDesc',
                    'bool_var': False,
                    'setup_kwargs_literal': setup_kwargs_literal,
                    'setup_kwargs': {'key1': "SetupKwargs_Key1_Value",
                                     'key2': ["list", "of", "test", "strings"],
                                     }
                    }

        patched = patch_string(setup_tpl, glo_vars)

        assert patched == textwrap.dedent('''\
        """ setup of ProjectDesc. """


        setup_kwargs = {
            'key1': 'SetupKwargs_Key1_Value',
            'key2': [
                'list',
                'of',
                'test',
                'strings',
            ],
        }
        setuptools.setup(**setup_kwargs)
        ''')

        glo_vars['bool_var'] = True

        patched = patch_string(setup_tpl, glo_vars)

        assert patched == textwrap.dedent('''\
        """ setup of ProjectDesc. """
        import sys
        print(f"SetUp {__name__=} {sys.executable=} {sys.argv=} {sys.path=}")
        setup_kwargs = {
            'key1': 'SetupKwargs_Key1_Value',
            'key2': [
                'list',
                'of',
                'test',
                'strings',
            ],
        }
        setuptools.setup(**setup_kwargs)
        ''')

    def test_project_templates_new_dev_req(self, cleanup_git_clone_cache, cons_app):
        old_tpls = CACHED_TPL_PROJECTS.copy()
        root_prj_imp_name = 'ae.ae'
        reg_tpls = CACHED_TPL_PROJECTS.copy()
        dev_reqs = []

        prj_tpls = project_templates(MODULE_PRJ, 'ae', {}, reg_tpls, dev_reqs)

        assert root_prj_imp_name + PROJECT_VERSION_SEP + prj_tpls[0]['version'] in reg_tpls
        assert 'aedev.module_tpls' + PROJECT_VERSION_SEP + "" in reg_tpls
        assert 'aedev.project_tpls' + PROJECT_VERSION_SEP + prj_tpls[1]['version'] in reg_tpls

        assert len(prj_tpls) == 2   # ae namespace root and project_tpls
        assert prj_tpls[0]['import_name'] == root_prj_imp_name
        assert prj_tpls[0]['version'] != ""   # latest PyPI version
        assert prj_tpls[0] == reg_tpls[root_prj_imp_name + PROJECT_VERSION_SEP + prj_tpls[0]['version']]
        assert prj_tpls[1]['import_name'] == 'aedev.project_tpls'
        assert prj_tpls[1]['version'] != ""   # latest PyPI version
        assert prj_tpls[1] == reg_tpls['aedev.project_tpls' + PROJECT_VERSION_SEP + prj_tpls[1]['version']]

        assert len(reg_tpls) == len(old_tpls) + 1  # + ae_ae namespace root
        reg_tpl = reg_tpls[root_prj_imp_name + PROJECT_VERSION_SEP + prj_tpls[0]['version']]
        assert reg_tpl['import_name'] == root_prj_imp_name
        assert reg_tpl['version'] == prj_tpls[0]['version']
        assert reg_tpl['tpl_path'].endswith(TEMPLATES_FOLDER)
        assert reg_tpl['register_message'] != ""
        reg_tpl = reg_tpls['aedev.module_tpls' + PROJECT_VERSION_SEP + ""]
        assert reg_tpl['import_name'] == 'aedev.module_tpls'
        assert reg_tpl['version'] == ""
        assert reg_tpl['tpl_path'] == ""
        assert reg_tpl['register_message'] != ""
        reg_tpl = reg_tpls['aedev.project_tpls' + PROJECT_VERSION_SEP + prj_tpls[1]['version']]
        assert reg_tpl['import_name'] == 'aedev.project_tpls'
        assert reg_tpl['version'] == prj_tpls[1]['version']
        assert reg_tpl['tpl_path'].endswith(TEMPLATES_FOLDER)
        assert reg_tpl['register_message'] != ""

        assert len(dev_reqs) == 2
        assert norm_name(root_prj_imp_name) + PROJECT_VERSION_SEP + prj_tpls[0]['version'] in dev_reqs
        assert norm_name('aedev.project_tpls') + PROJECT_VERSION_SEP + prj_tpls[1]['version'] in dev_reqs

        assert CACHED_TPL_PROJECTS == old_tpls

    def test_project_templates_dev_req_lock(self, cleanup_git_clone_cache, cons_app):
        dev_reqs = ('any_non_tpl_prj', )
        req_copy = tuple(dev_reqs)
        old_tpls = CACHED_TPL_PROJECTS.copy()
        reg_tpls = CACHED_TPL_PROJECTS.copy()

        prj_tpls = project_templates(MODULE_PRJ, 'ae', {}, reg_tpls, dev_reqs)

        assert len(prj_tpls) == 2
        assert dev_reqs == req_copy
        assert len(reg_tpls) == len(CACHED_TPL_PROJECTS) + 1  # + ae namespace root
        assert CACHED_TPL_PROJECTS == old_tpls

    def test_project_templates_dev_req_extendable(self, cleanup_git_clone_cache, cons_app):
        dev_reqs = ['any_non_tpl_prj']
        req_copy = dev_reqs.copy()
        reg_tpls = CACHED_TPL_PROJECTS.copy()
        assert reg_tpls

        prj_tpls = project_templates(MODULE_PRJ, 'aedev', {}, reg_tpls, dev_reqs)

        assert len(prj_tpls) == 2
        assert len(dev_reqs) == len(req_copy) + 2                   # added aedev.aedev root and aedev.project_tpls
        assert len(reg_tpls) == len(CACHED_TPL_PROJECTS) + 1        # added aedev.aedev root

    def test_register_template_aedev_root(self, cleanup_git_clone_cache, cons_app):
        nsn = "aedev"
        tpl_imp_name = nsn + "." + nsn
        pkg_name = norm_name(tpl_imp_name)
        tpl_path = os_path_join(pkg_name, nsn, nsn, TEMPLATES_FOLDER)
        dev_requires = []
        prj_tpls = []
        reg_tpls = CACHED_TPL_PROJECTS.copy()

        register_template(tpl_imp_name, {}, reg_tpls, dev_requires, prj_tpls)

        assert dev_requires
        assert dev_requires[0].startswith(pkg_name + PROJECT_VERSION_SEP)
        assert dev_requires[0].split(PROJECT_VERSION_SEP)[1]

        assert prj_tpls
        assert prj_tpls[0]['import_name'] == tpl_imp_name
        assert prj_tpls[0]['tpl_path'] != ""  # temporary dir path
        assert prj_tpls[0]['tpl_path'].endswith(tpl_path)
        assert prj_tpls[0]['version'] != ""   # latest PyPI version
        assert prj_tpls[0]['register_message'] != ""

        pkg_name, version = project_name_version(tpl_imp_name, list(reg_tpls.keys()))
        assert tpl_imp_name + PROJECT_VERSION_SEP + version in reg_tpls
        assert reg_tpls[tpl_imp_name + PROJECT_VERSION_SEP + version]['import_name'] == tpl_imp_name
        assert reg_tpls[tpl_imp_name + PROJECT_VERSION_SEP + version]['tpl_path'] != ""
        assert reg_tpls[tpl_imp_name + PROJECT_VERSION_SEP + version]['tpl_path'].endswith(tpl_path)
        assert reg_tpls[tpl_imp_name + PROJECT_VERSION_SEP + version]['version'] == version
        assert reg_tpls[tpl_imp_name + PROJECT_VERSION_SEP + version]['register_message'] != ""
        assert version in reg_tpls[tpl_imp_name + PROJECT_VERSION_SEP + version]['register_message']

    @skip_gitlab_ci
    def test_register_template_aedev_root_local(self, cleanup_git_clone_cache):
        nsn = "aedev"
        tpl_imp_name = nsn + "." + nsn
        pkg_name = norm_name(tpl_imp_name)
        pkg_path = "../" + pkg_name
        tpl_subdir = os_path_join(nsn, nsn, TEMPLATES_FOLDER)
        pkg_tpl_path = norm_path(os_path_join(pkg_path, tpl_subdir))
        dev_requires = []
        prj_tpls = []
        reg_tpls = CACHED_TPL_PROJECTS.copy()
        req_options = {template_path_option(tpl_imp_name): pkg_path}

        register_template(tpl_imp_name, req_options, reg_tpls, dev_requires, prj_tpls)

        assert not dev_requires     # local templates get never added to dev_requirements

        assert prj_tpls
        assert prj_tpls[0]['import_name'] == tpl_imp_name
        assert prj_tpls[0]['tpl_path'] == pkg_tpl_path
        assert prj_tpls[0]['tpl_path'].endswith(tpl_subdir)
        assert prj_tpls[0]['version'] == 'local'
        assert prj_tpls[0]['register_message'] != ""

        pkg_name, version = project_name_version(tpl_imp_name, list(reg_tpls.keys()))
        assert tpl_imp_name + PROJECT_VERSION_SEP + version in reg_tpls
        assert reg_tpls[tpl_imp_name + PROJECT_VERSION_SEP + version]['import_name'] == tpl_imp_name
        assert reg_tpls[tpl_imp_name + PROJECT_VERSION_SEP + version]['tpl_path'].endswith(tpl_subdir)
        assert reg_tpls[tpl_imp_name + PROJECT_VERSION_SEP + version]['tpl_path'] == pkg_tpl_path
        assert reg_tpls[tpl_imp_name + PROJECT_VERSION_SEP + version]['version'] == version
        assert reg_tpls[tpl_imp_name + PROJECT_VERSION_SEP + version]['register_message'] != ""
        assert version in reg_tpls[tpl_imp_name + PROJECT_VERSION_SEP + version]['register_message']

    def test_register_template_aedev_root_version(self, cleanup_git_clone_cache, cons_app):
        nsn = "aedev"
        version = "0.3.24"
        tpl_imp_name = nsn + "." + nsn
        pkg_name = norm_name(tpl_imp_name)
        tpl_path = os_path_join(pkg_name, nsn, nsn, TEMPLATES_FOLDER)
        dev_requires = []
        prj_tpls = []
        reg_tpls = CACHED_TPL_PROJECTS.copy()
        req_options = {template_version_option(tpl_imp_name): version}

        register_template(tpl_imp_name, req_options, reg_tpls, dev_requires, prj_tpls)

        assert dev_requires
        assert dev_requires[0].startswith(pkg_name + PROJECT_VERSION_SEP)
        assert dev_requires[0].split(PROJECT_VERSION_SEP)[1]

        assert prj_tpls
        assert prj_tpls[0]['import_name'] == tpl_imp_name
        assert prj_tpls[0]['tpl_path'] != ""
        assert prj_tpls[0]['tpl_path'].endswith(tpl_path)
        assert prj_tpls[0]['version'] == version
        assert prj_tpls[0]['register_message'] != ""

        pkg_name, version = project_name_version(tpl_imp_name, list(reg_tpls.keys()))
        assert tpl_imp_name + PROJECT_VERSION_SEP + version in reg_tpls
        assert reg_tpls[tpl_imp_name + PROJECT_VERSION_SEP + version]['import_name'] == tpl_imp_name
        assert reg_tpls[tpl_imp_name + PROJECT_VERSION_SEP + version]['tpl_path'] != ""
        assert reg_tpls[tpl_imp_name + PROJECT_VERSION_SEP + version]['tpl_path'].endswith(tpl_path)
        assert reg_tpls[tpl_imp_name + PROJECT_VERSION_SEP + version]['version'] == version
        assert reg_tpls[tpl_imp_name + PROJECT_VERSION_SEP + version]['register_message'] != ""
        assert version in reg_tpls[tpl_imp_name + PROJECT_VERSION_SEP + version]['register_message']

    def test_register_template_not_existing(self, cleanup_git_clone_cache):
        tpl_imp_name = "not.existing_package_tpls_imp_name"
        dev_requires = []
        prj_tpls = []
        reg_tpls = CACHED_TPL_PROJECTS.copy()

        register_template(tpl_imp_name, {}, reg_tpls, dev_requires, prj_tpls)

        assert not dev_requires
        assert not prj_tpls
        assert tpl_imp_name + PROJECT_VERSION_SEP in reg_tpls
        assert reg_tpls[tpl_imp_name + PROJECT_VERSION_SEP]['import_name'] == tpl_imp_name
        assert reg_tpls[tpl_imp_name + PROJECT_VERSION_SEP]['tpl_path'] == ""
        assert reg_tpls[tpl_imp_name + PROJECT_VERSION_SEP]['version'] == ""
        assert reg_tpls[tpl_imp_name + PROJECT_VERSION_SEP]['register_message'] != ""
        assert tpl_imp_name in reg_tpls[tpl_imp_name + PROJECT_VERSION_SEP]['register_message']

    def test_setup_kwargs_literal(self):
        kwargs = {'key1': "val1", 'key2': {'a': 1, 'b': "3"}}
        lit = setup_kwargs_literal(kwargs)
        assert lit[0] == "{"
        assert lit[1] == "\n"
        assert lit[2:14] == " " * 4 + "'key1': "
        assert lit[14:21] == "'val1',"
        assert lit[21:36] == "\n" + " " * 4 + "'key2': {\n"
        assert lit[35:52] == "\n" + " " * 8 + "'a': 1,\n"
        assert lit[51:70] == "\n" + " " * 8 + "'b': '3',\n"
        assert lit[-4:-2] == "},"
        assert lit[-2:] == "\n}"

    def test_template_path_option(self):
        nsn_name = 'nsn'
        por_name = 'nsn'
        import_name = nsn_name + "." + por_name

        assert template_path_option(import_name) == 'portions_namespace_root' + TPL_PATH_OPTION_SUFFIX

        por_name = "what_ever" + TPL_IMPORT_NAME_SUFFIX
        import_name = nsn_name + "." + por_name

        assert template_path_option(import_name) == norm_name(por_name) + TPL_PATH_OPTION_SUFFIX

    def test_template_version_option(self):
        import_name = 'xy.nsm.prj_name'

        assert template_version_option(import_name) == 'portions_namespace_root' + TPL_VERSION_OPTION_SUFFIX

        import_name += TPL_IMPORT_NAME_SUFFIX
        por_name = import_name.split('.')[-1]

        assert template_version_option(import_name) == norm_name(por_name) + TPL_VERSION_OPTION_SUFFIX


def test_temp_context_is_correctly_cleaned_up():
    assert not temp_context_folders(GIT_CLONE_CACHE_CONTEXT)
