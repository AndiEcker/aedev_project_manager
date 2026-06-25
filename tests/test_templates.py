""" project manager templates unit tests """
import os
import textwrap

from unittest.mock import patch, MagicMock

import pytest

from tests.conftest import skip_gitlab_ci

from ae.base import (
    DEF_PROJECT_PARENT_FOLDER, PY_EXT, PY_INIT, TEMPLATES_FOLDER,
    in_wd, norm_name, norm_path, os_path_basename, os_path_isdir, os_path_isfile, os_path_join,
    read_file, write_file)
from ae.core import main_app_instance, temp_context_cleanup, temp_context_folders
from ae.managed_files import (
    PATH_PREFIXES_ARGS_SEP, PUTTABLE_TEMPLATE_PATH_PFX, REFRESHABLE_TEMPLATE_MARKER,
    F_STRINGS_PATH_PFX, TEMPLATE_PLACEHOLDER_ID_PREFIX, TEMPLATE_PLACEHOLDER_ID_SUFFIX,
    TEMPLATE_PLACEHOLDER_ARGS_SUFFIX, TEMPLATE_INCLUDE_FILE_PLACEHOLDER_ID,
    deploy_template, patch_string)
from aedev.base import (
    PROJECT_VERSION_SEP, MODULE_PRJ, PACKAGE_PRJ, PARENT_PRJ, ROOT_PRJ, TEST_PROJECTS_PARENT_FOLDER,
    project_name_version)
from aedev.commands import GIT_CLONE_CACHE_CONTEXT, GIT_VERSION_TAG_PREFIX
from aedev.project_vars import PDV_REQ_DEV_FILE_NAME, ProjectDevVars, frozen_req_file_path

# noinspection PyProtectedMember
from aedev.project_manager.__main__ import _renew_prj_dir

from constants_and_fixtures import (
    app_pjm, app_pjm_debug, changed_repo_path, empty_repo_path, mocked_app_options, module_repo_path, pdv_with_email)

# noinspection PyProtectedMember
from aedev.project_manager.templates import (
    CACHED_TPL_PROJECTS, PATH_PREFIXES_PARSERS, SKIP_FOR_PORTIONS_PATH_PFX, SKIP_PRJ_TYPE_PATH_PFX,
    TPL_IMPORT_NAME_PREFIX, TPL_IMPORT_NAME_SUFFIX, TPL_PATH_OPTION_SUFFIX, TPL_VERSION_OPTION_SUFFIX,
    check_templates, clone_template_project, _get_template_vars, _log_check_outdated,
    path_pfx_place_into_package_path, path_pfx_skip_for_portions, path_pfx_skip_if_project_type,
    project_templates, register_template, setup_kwargs_literal, template_path_option, template_version_option)


def teardown_module():
    """ pytest test module teardown to clear registered template projects and to check if main app gets used. """
    print(f"##### {os_path_basename(__file__)} teardown_module BEG - {CACHED_TPL_PROJECTS=} {main_app_instance()=}")

    assert not CACHED_TPL_PROJECTS
    temp_context_cleanup()
    temp_context_cleanup(GIT_CLONE_CACHE_CONTEXT)

    print(f"##### {os_path_basename(__file__)} teardown_module END - {CACHED_TPL_PROJECTS=} {main_app_instance()=}")


@pytest.fixture
def cleanup_caches():
    """ clean up the template cache """
    assert not temp_context_folders(GIT_CLONE_CACHE_CONTEXT)
    yield
    temp_context_cleanup(GIT_CLONE_CACHE_CONTEXT)
    CACHED_TPL_PROJECTS.clear()


# noinspection PyUnusedLocal
def test_declaration_of_template_vars(cleanup_caches):
    assert isinstance(PUTTABLE_TEMPLATE_PATH_PFX, str)
    assert isinstance(REFRESHABLE_TEMPLATE_MARKER, str)
    assert isinstance(F_STRINGS_PATH_PFX, str)
    assert isinstance(TEMPLATE_PLACEHOLDER_ID_PREFIX, str)
    assert isinstance(TEMPLATE_PLACEHOLDER_ID_SUFFIX, str)
    assert isinstance(TEMPLATE_PLACEHOLDER_ARGS_SUFFIX, str)
    assert isinstance(TEMPLATE_INCLUDE_FILE_PLACEHOLDER_ID, str)


class TestHelpers:
    def test__get_template_vars(self):
        tpl_vars = _get_template_vars(pdv_with_email())

        assert isinstance(tpl_vars, dict)
        assert tpl_vars['TEST_PROJECTS_PARENT_FOLDER'] == TEST_PROJECTS_PARENT_FOLDER   # .gitlab-ci.yml pf project_tpls
        assert tpl_vars['frozen_req_file_path'] is frozen_req_file_path                 # .gitlab-ci.yml of project_tpls
        assert tpl_vars['setup_kwargs_literal'] == setup_kwargs_literal                 # in setup.py of project_tpls
        assert '_add_base_globals' in tpl_vars

    def test_app_options_namespace_module(self, cons_app, tmp_path):
        nsn = 'abc'
        parent_dir = os_path_join(str(tmp_path), DEF_PROJECT_PARENT_FOLDER)
        portion_name = 'tst_ns_mod'
        project_path = os_path_join(parent_dir, nsn + '_' + portion_name)
        module_path = os_path_join(project_path, nsn, portion_name + PY_EXT)
        app_options = {'repo_group': "tst_grp",
                       template_version_option(nsn + '.' + nsn): ""}

        write_file(module_path, f"mod_content = ''{os.linesep}__version__ = '3.3.3'{os.linesep}", make_dirs=True)

        pdv = pdv_with_email(project_path=project_path, **app_options)

        assert pdv['namespace_name'] == nsn
        assert pdv['project_name'] == nsn + '_' + portion_name
        assert pdv['package_path'] == os_path_join(norm_path(project_path), nsn, portion_name)
        assert pdv['project_path'] == norm_path(project_path)
        assert pdv['project_type'] == MODULE_PRJ
        assert pdv['repo_group'] == app_options['repo_group']
        assert pdv['version_file'] == norm_path(module_path)

        pdv = pdv_with_email(project_path=parent_dir, **app_options)

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

        write_file(os_path_join(package_path, PY_INIT),
                   f"pkg_ini_content = ''{os.linesep}__version__ = '6.3.6'{os.linesep}",
                   make_dirs=True)

        pdv = pdv_with_email(project_path=project_path, **app_options)

        assert pdv['namespace_name'] == nsn
        assert pdv['project_name'] == nsn + '_' + portion_name
        assert pdv['package_path'] == norm_path(package_path)
        assert pdv['project_path'] == norm_path(project_path)
        assert pdv['project_type'] == PACKAGE_PRJ
        assert pdv['repo_group'] == app_options['repo_group']
        assert pdv['version_file'] == norm_path(os_path_join(package_path, PY_INIT))

        app_options['namespace_name'] = nsn

        pdv = pdv_with_email(project_path=project_path, **app_options)

        assert pdv['namespace_name'] == nsn
        assert pdv['project_name'] == nsn + '_' + portion_name
        assert pdv['package_path'] == norm_path(package_path)
        assert pdv['project_path'] == norm_path(project_path)
        assert pdv['project_type'] == PACKAGE_PRJ
        assert pdv['repo_group'] == app_options['repo_group']
        assert pdv['version_file'] == norm_path(os_path_join(package_path, PY_INIT))

        app_options['namespace_name'] = ""

        pdv = pdv_with_email(project_path=parent_dir, **app_options)

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

        write_file(os_path_join(package_path, PY_INIT),
                   f"root_content = ''{os.linesep}__version__ = '9.9.3'{os.linesep}",
                   make_dirs=True)

        pdv = pdv_with_email(project_path=project_path, **app_options)

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

        pdv = pdv_with_email(project_path=project_path, **app_options)

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

        pdv = pdv_with_email(project_path=parent_dir, **app_options)

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

        app_options = {'repo_group': "tst_grp",
                       template_version_option(nsn + '.' + nsn): ""}

        write_file(os_path_join(root_pkg_path, PY_INIT),
                   f"root_content = ''{os.linesep}__version__ = '111.33.63'{os.linesep}",
                   make_dirs=True)
        write_file(os_path_join(root_prj_path, PDV_REQ_DEV_FILE_NAME),
                   nsn + '_' + project_name + os.linesep + nsn + '_' + module_name)

        write_file(os_path_join(package_pkg_path, PY_INIT),
                   f"pkg_content = ''{os.linesep}__version__ = '999.333.636'{os.linesep}",
                   make_dirs=True)
        write_file(os_path_join(package_pkg_path, package_extra_module_name + PY_EXT), "extra_content = ''")

        write_file(os_path_join(module_prj_path, nsn, module_name + PY_EXT),
                   f"mod_content = ''{os.linesep}__version__ = '6.9.699'{os.linesep}", make_dirs=True)

        pdv = pdv_with_email(project_path=root_prj_path, **app_options)

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

        pdv = pdv_with_email(project_path=root_prj_path, **app_options)

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

        pdv = pdv_with_email(project_path=parent_dir, **app_options)

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
        with pytest.warns(UserWarning) as captured_warning:
            with in_wd(str(tmp_path)):
                assert check_templates(app_pjm, ProjectDevVars(project_path=str(tmp_path))) is None

        # fewer warnings if tests are running by pjm (but not w/ same command line in shell/console or in PyCharm)
        err_cnt = len(captured_warning)
        assert err_cnt in (1, 3)
        if err_cnt == 1:
            assert "parent folder name" in str(captured_warning[0].message)
        else:
            assert "author name is missing" in str(captured_warning[0].message)
            assert "author email address is missing" in str(captured_warning[1].message)
            assert "parent folder name" in str(captured_warning[2].message)
            assert "not in parent_folders" in str(captured_warning[2].message)

    def test_check_templates_file_include_content(self, app_pjm, cleanup_caches, tmp_path):
        parent_dir = os_path_join(str(tmp_path), DEF_PROJECT_PARENT_FOLDER)
        tpl_pkg_path = norm_path(os_path_join(parent_dir, 'tst_tpls', TEMPLATES_FOLDER))
        tpl_file_name = "including_content.txt"
        tpl_file_path = os_path_join(tpl_pkg_path, PUTTABLE_TEMPLATE_PATH_PFX + F_STRINGS_PATH_PFX + tpl_file_name)
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

        tpl = f"{TEMPLATE_PLACEHOLDER_ID_PREFIX}{TEMPLATE_INCLUDE_FILE_PLACEHOLDER_ID}"
        tpl += f"{TEMPLATE_PLACEHOLDER_ID_SUFFIX}{included_file_name}{TEMPLATE_PLACEHOLDER_ARGS_SUFFIX}"
        write_file(tpl_file_path, tpl, make_dirs=True)

        write_file(included_file_name, included_file_content, make_dirs=True)

        os.mkdir(project_path)
        with in_wd(project_path):
            tmg = check_templates(app_pjm, pdv_with_email(project_type=MODULE_PRJ, project_templates=prj_templates))
            assert tmg
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

    def test_check_templates_file_include_default_with_pdv(self, app_pjm, cleanup_caches, mocked_app_options, tmp_path):
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
        tpl_file_path = os_path_join(tpl_pkg_path, PUTTABLE_TEMPLATE_PATH_PFX + F_STRINGS_PATH_PFX + patched_file)

        default = "include file default string"
        version = '6.699.987'

        mocked_app_options[template_version_option(tpl_imp_name)] = version
        mocked_app_options['namespace_name'] = namespace_name    # or ""

        write_file(os_path_join(package_path, portion_name + PY_EXT), "__version__ = '9.6.3'", make_dirs=True)
        write_file(os_path_join(project_path, PDV_REQ_DEV_FILE_NAME), norm_name(tpl_imp_name))

        tpl = "{TEMPLATE_PLACEHOLDER_ID_PREFIX}{TEMPLATE_INCLUDE_FILE_PLACEHOLDER_ID}"
        tpl += "{TEMPLATE_PLACEHOLDER_ID_SUFFIX}"
        tpl += f"not_existing_included_file_name.ext,{default}"
        tpl += "{TEMPLATE_PLACEHOLDER_ARGS_SUFFIX}"
        write_file(tpl_file_path, tpl, make_dirs=True)

        CACHED_TPL_PROJECTS[tpl_imp_name + PROJECT_VERSION_SEP + version] = {
            'import_name': tpl_imp_name, 'tpl_path': tpl_pkg_path, 'version': version,
            'register_message': "manually setup for unit testing"}

        pdv = pdv_with_email(project_path=project_path)

        with in_wd(project_path):
            tmg = check_templates(app_pjm, pdv)

        assert tmg
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

    def test_check_templates_log_check_outdated_diff_bytes(self):
        app_mock = MagicMock()

        _log_check_outdated(app_mock, [('f_nam.ext', b'old_bin', b'new_bin')], True)

        assert app_mock.po.call_count == 2
        assert len(app_mock.method_calls) == 2
        assert 'f_nam.ext' in app_mock.method_calls[0].args[0]
        assert 'old_bin' in app_mock.method_calls[1].args[0]
        assert 'new_bin' in app_mock.method_calls[1].args[0]

    def test_check_templates_log_check_ndiff_debug_or_verbose_false(self):
        app_mock = MagicMock()

        _log_check_outdated(app_mock, [('f_nam.ext', 'old_str', 'new_str')], False)

        assert app_mock.po.call_count == 2
        assert len(app_mock.method_calls) == 2
        assert 'f_nam.ext' in app_mock.method_calls[0].args[0]
        assert 'old_str' in app_mock.method_calls[1].args[0]
        assert 'new_str' in app_mock.method_calls[1].args[0]

    def test_check_templates_log_check_outdated_ndiff_verbose(self):
        app_mock = MagicMock()      # cae.verbose is True

        _log_check_outdated(app_mock, [('f_nam.ext', 'old_str', 'new_str')], True)

        assert app_mock.po.call_count == 2
        assert len(app_mock.method_calls) == 2
        assert 'f_nam.ext' in app_mock.method_calls[0].args[0]
        assert 'old_str' in app_mock.method_calls[1].args[0]
        assert 'new_str' in app_mock.method_calls[1].args[0]

    def test_check_templates_log_check_outdated_unified_diff_debug(self):
        app_mock = MagicMock()
        app_mock.verbose = False

        _log_check_outdated(app_mock, [('f_nam.ext', 'old_str', 'new_str')], True)

        assert app_mock.po.call_count == 2
        assert len(app_mock.method_calls) == 2
        assert 'f_nam.ext' in app_mock.method_calls[0].args[0]
        assert 'old_str' in app_mock.method_calls[1].args[0]
        assert 'new_str' in app_mock.method_calls[1].args[0]

    def test_check_templates_log_check_outdated_context_diff(self):
        app_mock = MagicMock()
        app_mock.verbose = False
        app_mock.debug = False

        _log_check_outdated(app_mock, [('f_nam.ext', 'old_str', 'new_str')], True)

        assert app_mock.po.call_count == 2
        assert len(app_mock.method_calls) == 2
        assert 'f_nam.ext' in app_mock.method_calls[0].args[0]
        assert 'old_str' in app_mock.method_calls[1].args[0]
        assert 'new_str' in app_mock.method_calls[1].args[0]

    def test_check_templates_log_check_summary(self, app_pjm_debug, capsys, cleanup_caches, module_repo_path):
        pdv = pdv_with_email(project_path=module_repo_path)
        # uncomment next line to test w/ full coverage using the new path-prefix-ids local:
        # pdv['main_app_options'] = {'project_tpls_project_path': "~/src/aedev_project_tpls"}
        write_file(os.path.join(pdv['project_path'], 'CONTRIBUTING.rst'), f"{REFRESHABLE_TEMPLATE_MARKER} - outdated")
        # write_file(os.path.join(pdv['project_path'], '.gitignore'), f"{REFRESHABLE_TEMPLATE_MARKER} - outdated")
        por_name = pdv['portion_name']

        with in_wd(module_repo_path):
            man = check_templates(app_pjm_debug, pdv)
            assert man

        output = capsys.readouterr().out
        assert por_name in output

        with in_wd(module_repo_path):
            man.deploy()
            assert check_templates(app_pjm_debug, pdv)  # test/coverage of man.checked_files console output

        output = capsys.readouterr().out
        assert por_name in output
        assert " are up-to-date" in output

    @patch('aedev.project_manager.templates.debug_or_verbose', return_value=False)
    def test_check_templates_log_debug_disabled(self, _, app_pjm, capsys, cleanup_caches, module_repo_path):
        pdv = pdv_with_email(project_path=module_repo_path)
        write_file(os.path.join(pdv['project_path'], 'CONTRIBUTING.rst'), f"{REFRESHABLE_TEMPLATE_MARKER} - outdated")
        por_name = pdv['portion_name']

        with in_wd(module_repo_path):
            assert check_templates(app_pjm, pdv)

        output, _err = capsys.readouterr()
        assert por_name in output

    def test_check_templates_no_prj(self, app_pjm, cleanup_caches, empty_repo_path, changed_repo_path):
        with in_wd(empty_repo_path):
            assert not check_templates(app_pjm, pdv_with_email(project_path=empty_repo_path))
        with in_wd(changed_repo_path):
            assert not check_templates(app_pjm, pdv_with_email(project_path=changed_repo_path))

    def test_check_templates_test_registered(self, cleanup_caches, cons_app, recwarn, tmp_path):
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
        tpl_file_for_all = PUTTABLE_TEMPLATE_PATH_PFX + F_STRINGS_PATH_PFX + file_for_all
        for tpl_reg in prj_tpls:
            tpl_path = os_path_join(tpl_reg['tpl_path'], deep_sub_dir)
            write_file(os_path_join(tpl_path, tpl_file_for_all), tpl_reg['tpl_path'], make_dirs=True)
        tpl_file = os_path_join(project_path, deep_sub_dir, file_for_all)
        pdv = ProjectDevVars(**{'namespace_name': namespace, 'project_path': project_path, 'project_type': PACKAGE_PRJ,
                                'project_templates': prj_tpls})

        with in_wd(project_path):
            tmg = check_templates(cons_app, pdv)
            assert tmg
            assert set(tmg.deploy_files.keys()) == {norm_path(tpl_file)}
            assert not os_path_isfile(tpl_file)
            tmg.deploy()
            assert os_path_isfile(tpl_file)
            content = read_file(tpl_file)
        assert prj_tpls[0]['tpl_path'] in content
        assert REFRESHABLE_TEMPLATE_MARKER in content

        # fewer warnings if tests are running by pjm (but not w/ same command line in shell/console or in PyCharm)
        err_cnt = len(recwarn)
        assert err_cnt in (2, 4)
        assert "author name is missing" in str(recwarn[0].message)
        assert "author email address is missing" in str(recwarn[1].message)
        if err_cnt == 4:
            assert "author name is missing" in str(recwarn[2].message)
            assert "author email address is missing" in str(recwarn[3].message)

    def test_clone_template_project(self, cleanup_caches, cons_app):
        tpl_path = clone_template_project('aedev.project_tpls', GIT_VERSION_TAG_PREFIX + '0.3.36')
        assert tpl_path
        assert os_path_isdir(tpl_path)
        assert os_path_basename(tpl_path) == TEMPLATES_FOLDER

    def test_clone_template_project_for_apps(self, cleanup_caches, cons_app):
        tpl_path = clone_template_project('aedev.app_tpls', GIT_VERSION_TAG_PREFIX + '0.3.16')
        assert tpl_path
        assert os_path_isdir(tpl_path)
        assert os_path_basename(tpl_path) == TEMPLATES_FOLDER

    def test_deploy_template_sfp_path_pfx_remove_and_spt_in_sub_dir(self, cleanup_caches, tmp_path):
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
        prefixes = SKIP_FOR_PORTIONS_PATH_PFX + SKIP_PRJ_TYPE_PATH_PFX + ROOT_PRJ + PATH_PREFIXES_ARGS_SEP
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

    def test_path_pfx_place_into_package_path(self):
        mf = MagicMock()
        rel_path = 'rel_path'

        with patch('aedev.project_manager.templates.os_path_relpath', return_value=rel_path):
            path_pfx_place_into_package_path(mf)

        mf.extend_dst_file_path.assert_called_once_with(rel_path)

    def test_path_pfx_skip_for_portions(self):
        mf = MagicMock()

        path_pfx_skip_for_portions(mf)

        mf.skip.assert_called_once()

    def test_path_pfx_skip_if_project_type(self):
        mf = MagicMock()
        # the following code line does: mf.manager.context_vars['project_type'] = MODULE_PRJ
        mf.manager.context_vars.__getitem__.return_value = MODULE_PRJ

        path_pfx_skip_if_project_type(mf, MODULE_PRJ)

        mf.skip.assert_called_once()

    def test_project_templates_new_dev_req(self, cleanup_caches, app_pjm):
        old_tpls = CACHED_TPL_PROJECTS.copy()
        root_prj_imp_name = 'ae.ae'
        reg_tpls = CACHED_TPL_PROJECTS.copy()
        dev_reqs = []

        prj_tpls = project_templates(MODULE_PRJ, 'ae', {}, reg_tpls, dev_reqs)

        assert root_prj_imp_name + PROJECT_VERSION_SEP + prj_tpls[0]['version'] in reg_tpls
        assert 'aedev.module_tpls' + PROJECT_VERSION_SEP + "" in reg_tpls

        assert prj_tpls[0]['import_name'] == root_prj_imp_name
        assert prj_tpls[0]['version'] != ""   # latest PyPI version
        assert prj_tpls[0] == reg_tpls[root_prj_imp_name + PROJECT_VERSION_SEP + prj_tpls[0]['version']]

        assert len(prj_tpls) == 2   # ae namespace root and project_tpls
        assert 'aedev.project_tpls' + PROJECT_VERSION_SEP + prj_tpls[1]['version'] in reg_tpls
        assert prj_tpls[1]['import_name'] == 'aedev.project_tpls'
        assert prj_tpls[1]['version'] != ""   # latest PyPI version
        assert prj_tpls[1] == reg_tpls['aedev.project_tpls' + PROJECT_VERSION_SEP + prj_tpls[1]['version']]

        assert len(reg_tpls) == len(old_tpls) + 3  # added ae_ae, aedev_module_tpls, aedev_project_tpls
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

    def test_project_templates_dev_req_lock(self, cleanup_caches, cons_app):
        dev_reqs = ('any_non_tpl_prj', )
        req_copy = tuple(dev_reqs)
        old_tpls = CACHED_TPL_PROJECTS.copy()
        reg_tpls = CACHED_TPL_PROJECTS.copy()

        prj_tpls = project_templates(MODULE_PRJ, 'ae', {}, reg_tpls, dev_reqs)

        assert len(prj_tpls) == 2
        assert dev_reqs == req_copy
        assert len(reg_tpls) == len(CACHED_TPL_PROJECTS) + 3  # added ae_ae, aedev_module_tpls, aedev_project_tpls
        assert CACHED_TPL_PROJECTS == old_tpls

    def test_project_templates_dev_req_extendable(self, cleanup_caches, cons_app):
        dev_reqs = ['any_non_tpl_prj']
        req_copy = dev_reqs.copy()
        reg_tpls = CACHED_TPL_PROJECTS.copy()
        assert not reg_tpls

        prj_tpls = project_templates(MODULE_PRJ, 'aedev', {}, reg_tpls, dev_reqs)

        assert len(prj_tpls) == 2
        assert len(dev_reqs) == len(req_copy) + 2               # added aedev.aedev root and aedev.project_tpls
        assert len(reg_tpls) == len(CACHED_TPL_PROJECTS) + 3    # added aedev.aedev root, module and aedev.project_tpls

    def test_register_template_aedev_root(self, cleanup_caches, cons_app):
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
    def test_register_template_aedev_root_local(self, cleanup_caches):
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

    def test_register_template_aedev_root_version(self, cleanup_caches, cons_app):
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

    def test_register_template_not_existing(self, cleanup_caches):
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

    def test_register_template_with_path_option(self, cleanup_caches, tmp_path):
        nsn = "xyz"
        tpl_imp_name = nsn + "." + nsn
        tpl_pkg_path = str(tmp_path)
        tpl_src_path = os_path_join(tpl_pkg_path, nsn, nsn, TEMPLATES_FOLDER)
        os.makedirs(tpl_src_path)
        req_options = {template_path_option(tpl_imp_name): tpl_pkg_path}
        reg_tpls = CACHED_TPL_PROJECTS.copy()
        version = 'local'
        tpl_id = f"{tpl_imp_name}{PROJECT_VERSION_SEP}{version}"
        dev_requires = [tpl_id]
        prj_tpls = []

        register_template(tpl_imp_name, req_options, reg_tpls, dev_requires, prj_tpls)

        assert tpl_id in reg_tpls
        assert reg_tpls[tpl_id]['import_name'] == tpl_imp_name
        assert reg_tpls[tpl_id]['tpl_path'] == tpl_src_path
        assert reg_tpls[tpl_id]['version'] == version
        assert tpl_imp_name in reg_tpls[tpl_id]['register_message']

    def test_register_template_with_version_from_dev_requirements(self, cleanup_caches):
        nsn = "aedev"
        tpl_imp_name = nsn + "." + nsn
        version = "0.1.2.3"
        tpl_id = f"{tpl_imp_name}{PROJECT_VERSION_SEP}{version}"
        dev_requires = [tpl_id]
        prj_tpls = []
        reg_tpls = CACHED_TPL_PROJECTS.copy()

        register_template(tpl_imp_name, {}, reg_tpls, dev_requires, prj_tpls)

        assert tpl_id in reg_tpls
        assert reg_tpls[tpl_id]['import_name'] == tpl_imp_name
        assert reg_tpls[tpl_id]['tpl_path'] == ""
        assert reg_tpls[tpl_id]['version'] == version
        assert reg_tpls[tpl_id]['register_message'] != ""
        assert tpl_imp_name in reg_tpls[tpl_id]['register_message']

    def test_setup_kwargs_literal(self):
        kwargs = {'key1': "val1", 'key2': {'a': 1, 'b': "3"}}

        lit = setup_kwargs_literal(kwargs)

        assert lit[0] == "{"
        assert lit[1] == os.linesep
        assert lit[2:14] == " " * 4 + "'key1': "
        assert lit[14:21] == "'val1',"
        assert lit[21:36] == os.linesep + " " * 4 + "'key2': {" + os.linesep
        assert lit[35:52] == os.linesep + " " * 8 + "'a': 1," + os.linesep
        assert lit[51:70] == os.linesep + " " * 8 + "'b': '3'," + os.linesep
        assert lit[-4:-2] == "},"
        assert lit[-2:] == os.linesep + "}"

    def test_setup_kwargs_literal_long_description(self):
        kwargs = {'key1': "val1", 'long_description': {'a': 1, 'b': "3"}}

        lit = setup_kwargs_literal(kwargs)

        assert 'README.md' in lit

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
