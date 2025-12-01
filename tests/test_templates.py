""" project manager templates unit tests """
import os
import textwrap

import pytest

from tests.conftest import skip_gitlab_ci

from ae.base import (
    DEF_PROJECT_PARENT_FOLDER, PY_EXT, PY_INIT, TEMPLATES_FOLDER,
    norm_name, norm_path, os_path_basename, os_path_dirname, os_path_isdir, os_path_isfile, os_path_join,
    read_file, write_file)
from ae.core import main_app_instance, temp_context_cleanup, temp_context_folders
from ae.template import (
    OUTSOURCED_FILE_NAME_PREFIX, OUTSOURCED_MARKER, SKIP_IF_PORTION_DST_NAME_PREFIX, SKIP_PRJ_TYPE_FILE_NAME_PREFIX,
    TPL_FILE_NAME_PREFIX, TEMPLATE_PLACEHOLDER_ID_PREFIX, TEMPLATE_PLACEHOLDER_ID_SUFFIX,
    TEMPLATE_PLACEHOLDER_ARGS_SUFFIX, TEMPLATE_INCLUDE_FILE_PLACEHOLDER_ID,
    deploy_template, patch_string)
from aedev.base import (
    PROJECT_VERSION_SEP, MODULE_PRJ, PACKAGE_PRJ, PARENT_PRJ, ROOT_PRJ, project_name_version)
from aedev.commands import GIT_CLONE_CACHE_CONTEXT, GIT_VERSION_TAG_PREFIX
from aedev.project_vars import PDV_REQ_DEV_FILE_NAME, ProjectDevVars

from aedev.project_manager.templates import (
    CACHED_TPL_PROJECTS, TPL_IMPORT_NAME_SUFFIX, TPL_PATH_OPTION_SUFFIX, TPL_VERSION_OPTION_SUFFIX,
    clone_template_project, project_templates, register_template,
    setup_kwargs_literal, template_path_option, template_version_option)


def teardown_module():
    """ pytest test module teardown to clear registered template projects and to check if main app gets used. """
    print(f"##### {os_path_basename(__file__)} teardown_module BEG - {CACHED_TPL_PROJECTS=} {main_app_instance()=}")

    CACHED_TPL_PROJECTS.clear()         # remove registered template projects from ae.template module
    temp_context_cleanup()
    temp_context_cleanup(GIT_CLONE_CACHE_CONTEXT)

    print(f"##### {os_path_basename(__file__)} teardown_module END - {CACHED_TPL_PROJECTS=} {main_app_instance()=}")


@pytest.fixture
def clean_temp_dirs():
    assert not temp_context_folders(GIT_CLONE_CACHE_CONTEXT)
    yield
    temp_context_cleanup(GIT_CLONE_CACHE_CONTEXT)


def test_declaration_of_template_vars():
    assert isinstance(OUTSOURCED_FILE_NAME_PREFIX, str)
    assert isinstance(OUTSOURCED_MARKER, str)
    assert isinstance(TPL_FILE_NAME_PREFIX, str)
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

    def test_clone_template_project(self, clean_temp_dirs, cons_app):
        tpl_path = clone_template_project('aedev.project_tpls', GIT_VERSION_TAG_PREFIX + '0.3.36')
        assert tpl_path
        assert os_path_isdir(tpl_path)
        assert os_path_basename(tpl_path) == TEMPLATES_FOLDER

    def test_clone_template_project_for_apps(self, clean_temp_dirs, cons_app):
        tpl_path = clone_template_project('aedev.app_tpls', GIT_VERSION_TAG_PREFIX + '0.3.16')
        assert tpl_path
        assert os_path_isdir(tpl_path)
        assert os_path_basename(tpl_path) == TEMPLATES_FOLDER

    def test_deploy_template_sfp_prefix_remove_and_spt_in_sub_dir(self, tmp_path):
        parent_dir = os_path_join(str(tmp_path), DEF_PROJECT_PARENT_FOLDER)
        src_dir = os_path_join(parent_dir, 'tpl_src_prj_dir')
        tpl_dir = os_path_join(src_dir, TEMPLATES_FOLDER)
        sub_dir_folder = 'sub_dir'
        tpl_sub_dir = os_path_join(tpl_dir, sub_dir_folder)
        prefixes = SKIP_IF_PORTION_DST_NAME_PREFIX + SKIP_PRJ_TYPE_FILE_NAME_PREFIX
        file_name = prefixes + ROOT_PRJ + "_template_file_name.xyz"
        src_file = os_path_join(tpl_sub_dir, file_name)
        content = "template file content"
        dst_dir = os_path_join(parent_dir, 'dst')
        new_pdv = {'project_path': dst_dir, 'project_type': ROOT_PRJ}
        dst_files = set()
        write_file(src_file, content, make_dirs=True)
        os.makedirs(dst_dir)

        assert not deploy_template(src_file, sub_dir_folder, "", new_pdv, dst_files=dst_files)

        assert not dst_files        # skipped deploy

        new_pdv['project_type'] = MODULE_PRJ

        assert deploy_template(src_file, sub_dir_folder, "", new_pdv, dst_files=dst_files)

        assert dst_files            # not skipped deploy
        dst_file = os_path_join(dst_dir, sub_dir_folder, file_name[len(prefixes) + len(ROOT_PRJ) + 1:])
        assert os_path_isfile(dst_file)
        assert read_file(dst_file) == content
        assert norm_path(dst_file) in dst_files

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

    def test_project_templates_new_dev_req(self, clean_temp_dirs, cons_app):
        assert not CACHED_TPL_PROJECTS      # first reference to this cache in this test module - should be empty
        root_prj_imp_name = 'ae.ae'
        reg_tpls = CACHED_TPL_PROJECTS.copy()
        dev_reqs = []

        prj_tpls = project_templates(MODULE_PRJ, 'ae', {}, reg_tpls, dev_reqs)

        assert root_prj_imp_name + PROJECT_VERSION_SEP + prj_tpls[0]['version'] in reg_tpls
        assert 'aedev.module_tpls' + PROJECT_VERSION_SEP + "" in reg_tpls
        assert 'aedev.project_tpls' + PROJECT_VERSION_SEP + prj_tpls[1]['version'] in reg_tpls

        assert len(prj_tpls) == 2   # ae namespace root and tpl_project
        assert prj_tpls[0]['import_name'] == root_prj_imp_name
        assert prj_tpls[0]['version'] != ""   # latest PyPI version
        assert prj_tpls[0] == reg_tpls[root_prj_imp_name + PROJECT_VERSION_SEP + prj_tpls[0]['version']]
        assert prj_tpls[1]['import_name'] == 'aedev.project_tpls'
        assert prj_tpls[1]['version'] != ""   # latest PyPI version
        assert prj_tpls[1] == reg_tpls['aedev.project_tpls' + PROJECT_VERSION_SEP + prj_tpls[1]['version']]

        assert len(reg_tpls) == 3
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

        assert not CACHED_TPL_PROJECTS

    def test_project_templates_dev_req_lock(self, clean_temp_dirs, cons_app):
        dev_reqs = ('any_non_tpl_prj', )
        req_copy = tuple(dev_reqs)
        reg_tpls = CACHED_TPL_PROJECTS.copy()

        prj_tpls = project_templates(MODULE_PRJ, 'ae', {}, reg_tpls, dev_reqs)

        assert len(prj_tpls) == 2
        assert dev_reqs == req_copy
        assert len(reg_tpls) == len(CACHED_TPL_PROJECTS) + 3  # ae namespace root, module_tpls and project_tpls
        assert not CACHED_TPL_PROJECTS

    def test_project_templates_dev_req_extendable(self, clean_temp_dirs, cons_app):
        dev_reqs = ['any_non_tpl_prj']
        req_copy = dev_reqs.copy()
        reg_tpls = CACHED_TPL_PROJECTS.copy()
        assert not reg_tpls and not CACHED_TPL_PROJECTS

        prj_tpls = project_templates(MODULE_PRJ, 'aedev', {}, reg_tpls, dev_reqs)

        assert len(prj_tpls) == 2
        assert len(dev_reqs) == len(req_copy) + 2                   # added aedev and project_tpls
        assert len(reg_tpls) == len(CACHED_TPL_PROJECTS) + 3    # .. and module_tpls without version
        assert not CACHED_TPL_PROJECTS

        try:
            # cleanup because git_clone would fail because of non-empty temp destination dir/folder
            temp_context_cleanup(GIT_CLONE_CACHE_CONTEXT)
            prj_tpls = project_templates(MODULE_PRJ, 'aedev', {}, CACHED_TPL_PROJECTS, dev_reqs)

            assert len(prj_tpls) == 2
            assert len(reg_tpls) == len(CACHED_TPL_PROJECTS)
            assert reg_tpls != CACHED_TPL_PROJECTS  # only temp dir paths are new/changed
            assert len(dev_reqs) == len(req_copy) + 2
        finally:
            CACHED_TPL_PROJECTS.clear()

    def test_register_template_aedev_root(self, clean_temp_dirs, cons_app):
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

        assert not CACHED_TPL_PROJECTS

    @skip_gitlab_ci
    def test_register_template_aedev_root_local(self, clean_temp_dirs):
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

    def test_register_template_aedev_root_version(self, clean_temp_dirs, cons_app):
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

    def test_register_template_not_existing(self, clean_temp_dirs):
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
