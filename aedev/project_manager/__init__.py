"""
create and maintain Python projects locally and remotely
========================================================

this init module provides the project version number, and information on how to change/extend the code base of the
project-manager (``pjm``) tool.

the installation and usage of this tool gets explained `in its user manual document
<https://aedev.readthedocs.io/en/latest/man/project_manager.html>`__.

its documentation and implementation (constants, functions and classes) is bundled in
the :mod:`the main module <aedev.project_manager.__main__>`.


define a new action
-------------------

to add a new action you only need to declare a new method or function decorated with the :func:`_action` decorator. the
decorator will automatically register and integrate the new action into the ``pjm`` tool.

the help texts of an action gets compiled automatically from the docstring of the action function.
"""


__version__ = '0.3.6'
