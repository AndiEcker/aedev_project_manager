# THIS FILE IS EXCLUSIVELY MAINTAINED by the project aedev.project_tpls v0.3.59
""" setup of aedev namespace package portion project_manager: create and maintain Python projects locally and remotely. """
# noinspection PyUnresolvedReferences
import sys
print(f"SetUp {__name__=} {sys.executable=} {sys.argv=} {sys.path=}")

# noinspection PyUnresolvedReferences
import setuptools

setup_kwargs = {
    'author': 'AndiEcker',
    'author_email': 'aecker2@gmail.com',
    'classifiers': [       'Development Status :: 3 - Alpha', 'Natural Language :: English', 'Operating System :: OS Independent',
        'Programming Language :: Python', 'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.12', 'Topic :: Software Development :: Libraries :: Python Modules',
        'Typing :: Typed'],
    'description': 'aedev namespace package portion project_manager: create and maintain Python projects locally and remotely',
    'entry_points': {       'console_scripts': [       'pjm = aedev.project_manager.__main__:main',
                                   'project-manager = aedev.project_manager.__main__:main']},
    'extras_require': {       'dev': [       'aedev_project_tpls', 'aedev_aedev', 'anybadge', 'coverage-badge', 'aedev_project_manager',
                       'flake8', 'mypy', 'pylint', 'pytest', 'pytest-cov', 'pytest-django', 'typing',
                       'types-setuptools'],
        'docs': [],
        'tests': [       'anybadge', 'coverage-badge', 'aedev_project_manager', 'flake8', 'mypy', 'pylint', 'pytest',
                         'pytest-cov', 'pytest-django', 'typing', 'types-setuptools']},
    'install_requires': [       'anybadge', 'coverage', 'coverage-badge', 'flake8', 'mypy', 'packaging', 'Pillow', 'types-Pillow', 'PyGithub',
        'pylint', 'pytest', 'pytest-cov', 'python-gitlab', 'requests', 'requests-toolbelt', 'setuptools', 'ae_base==0.3.73',
        'ae_files==0.3.25', 'ae_paths==0.3.43', 'ae_dynamicod==0.3.15', 'ae_literal==0.3.35', 'ae_updater==0.3.17', 'ae_core==0.3.76', 'ae_console==0.3.85', 'ae_shell==0.3.7',
        'ae_templates==0.3.1', 'ae_dev_ops==0.3.8', 'ae_pythonanywhere==0.3.1'],
    'keywords': ['configuration', 'development', 'environment', 'productivity'],
    'license': 'GPL-3.0-or-later',
    'long_description': ('# project_manager command line tool\n'
 '\n'
 'simplifies your programming workflow, in order to:\n'
 '\n'
 '    * clone or fork projects from GitLab or GitHub\n'
 '    * push bug fixes and new features of projects to GitLab or GitHub\n'
 '    * request a MR (merge request) (or a PR (pull request) at GitHub)\n'
 '    * publish packages to [PyPI](https://pypi.org) or [PyPI Test](https://test.pypi.org)\n'
 '    * deploy Django apps to [PythonAnywhere](https://pythonanywhere.com)  \n'
 '    * run resource checks (i18n, images, sounds)\n'
 '    * run unit and integration tests (with coverage reports)\n'
 '    * use templates to create and maintain code, resource and configuration files\n'
 '    * bulk refresh/update of mulitple projects, e.g. your namespace portions projects (:pep:`420`)\n'
 '\n'
 'for more detailed information see the\n'
 '[manual](https://aedev.readthedocs.io/en/latest/man/project_manager.html "project manager manual").\n'
 '\n'
 'the source code is available at [Gitlab](https://gitlab.com/aedev-group/aedev_project_manager)\n'
 'maintained by the user group [aedev-group](https://gitlab.com/aedev-group).\n'
 '\n'
 'this project is implemented in pure Python code and based on some portions of the\n'
 '[__ae__ namespace(Application Environment)](https://ae.readthedocs.io "ae namespace portions on rtd").\n'),
    'long_description_content_type': 'text/markdown',
    'name': 'aedev_project_manager',
    'package_data': {'': []},
    'packages': ['aedev.project_manager'],
    'project_urls': {       'Bug Tracker': 'https://gitlab.com/aedev-group/aedev_project_manager/-/issues',
        'Documentation': 'https://aedev.readthedocs.io/en/latest/_autosummary/aedev.project_manager.html',
        'Repository': 'https://gitlab.com/aedev-group/aedev_project_manager',
        'Source': 'https://aedev.readthedocs.io/en/latest/_modules/aedev/project_manager.html'},
    'python_requires': '>=3.9',
    'url': 'https://gitlab.com/aedev-group/aedev_project_manager',
    'version': '0.3.6',
    'zip_safe': True,
}

if __name__ == "__main__":
    setuptools.setup(**setup_kwargs)
    pass
