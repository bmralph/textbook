""" Course utility functions
"""

import os
import os.path as op
import sys
from glob import iglob
import shutil
import re
import urllib.parse
from contextlib import contextmanager

import yaml

import nbformat
import jupytext
from nbconvert.preprocessors import ExecutePreprocessor
from jinja2 import Template

from rmdex.exerciser import (make_exercise, make_solution, write_utf8,
                             read_utf8)

HERE = op.dirname(op.realpath(__file__))
SITE_ROOT = op.realpath(op.join(HERE, '..'))
sys.path.append(HERE)

import grade_oknb as gok


TEMPLATE_RE = re.compile(r'_template\.Rmd$')


@contextmanager
def cd(newdir):
    prevdir = os.getcwd()
    os.chdir(os.path.expanduser(newdir))
    try:
        yield
    finally:
        os.chdir(prevdir)


def get_site_dict(site_config):
    with open(site_config, 'r') as ff:
        site = yaml.load(ff.read(), Loader=yaml.SafeLoader)
    # Get full baseurl from _config.yml format.
    if not site['baseurl'].startswith('http') and 'url' in site:
        site['baseurl'] = site['url'] + site['baseurl']
    for path_key in ('org_path',):
        if path_key in site:
            site[path_key] = op.expanduser(site[path_key])
    return site


def find_site_config(dir_path, filenames=('course.yml',
                                          '_course.yml',
                                          '_config.yml')):
    """ Iterate to parents to locate one of filenames specified in `filenames`.
    """
    dir_path = op.abspath(dir_path)
    while True:
        for fn in filenames:
            pth = op.join(dir_path, fn)
            if op.isfile(pth):
                return pth
        prev_dir_path = dir_path
        dir_path = op.abspath(op.join(dir_path, '..'))
        if (dir_path == prev_dir_path or  # We hit root.
            not prev_dir_path.startswith(dir_path)): # We hit fs boundary.
            break
    return None


def proc_config(in_path=None, site_config=None, out_path=None):
    if site_config is None:
       site_config = find_site_config(in_path)
    site_dict = get_site_dict(site_config) if site_config else {}
    if out_path is None:
        out_path = site_dict.get('org_path')
    if out_path is None:
        raise RuntimeError(
            'Must specify out path or "org_path" in config file\n'
            f'Config file is {site_config}'
        )
    return site_dict, out_path


def find_notebook(path):
    ipynbs = list(iglob(op.join(path, '*.ipynb')))
    rmds = list(iglob(op.join(path, '*.Rmd')))
    both = ipynbs + rmds
    if len(both) == 0:
        raise RuntimeError(f'Cannot find notebook files in {path}')
    if len(both) == 1:
        return both[0]
    if len(ipynbs) == 1 and len(rmds) == 1:
        # Look for one pair of matching ipynb and Rmd files.
        ipynb, rmd = both
        if op.splitext(ipynb)[0] == op.splitext(rmd)[0]:
            return ipynb
    fns = '\n'.join(both)
    raise RuntimeError(f'Too many notebook files in {path}:\n{fns}')


def build_url(fn, site_dict):
    if op.isdir(fn):
        fn = find_notebook(fn)
    nb_path, nb_basen = op.split(op.abspath(fn))
    root, ext = op.splitext(nb_basen)
    if ext not in ('.Rmd', '.ipynb'):
        raise RuntimeError(f'Is {fn} really a notebook?')
    repo = op.basename(nb_path)
    s_d = site_dict
    repo_url = urllib.parse.quote(
        f'{s_d["git_root"]}/{s_d["org_name"]}/{repo}')
    hub_suffix = 'hub/user-redirect/git-pull?repo='
    return f'{site_dict["jh_root"]}/{hub_suffix}{repo_url}&subPath={nb_basen}'


def execute_nb(nb, path, nbargs=None):
    nbargs = {} if nbargs is None else nbargs
    ep = ExecutePreprocessor(**nbargs)
    ep.preprocess(nb, {'metadata': {'path': path}})
    return nb


def clear_outputs(nb):
    for cell in nb['cells']:
        if cell['cell_type'] == 'code':
            cell['outputs'] = []
    return nb


def path_of(fname):
    return op.split(op.abspath(fname))[0]


def clear_directory(fname):
    path = path_of(fname)
    for basename in ('.ok_storage',):
        pth = op.join(path, basename)
        if op.exists(pth):
            os.unlink(pth)
    pycache = op.join(path, 'tests', '__pycache__')
    if op.isdir(pycache):
        shutil.rmtree(pycache)


def good_fname(fname, exclude_exts=()):
    fn = op.basename(fname)
    froot, ext = op.splitext(fn)
    if froot.startswith('.'):
        return False
    if ext in ('.pyc',) + exclude_exts:
        return False
    if froot.startswith('test_'):
        return False
    if froot.startswith('notes'):
        return False
    if froot.endswith('solution'):
        return False
    if froot.endswith('template'):
        return False
    if fn in ('__pycache__',
              'tests-extended',
              'Makefile'):
        return False
    return True


def ipynb_fname(fname):
    froot, ext = op.splitext(fname)
    return froot + '.ipynb'


HTML_COMMENT_RE = re.compile(r'<!--(.*?)-->', re.M | re.DOTALL)


def clear_md_comments(nb):
    """ Strip HTML comments using regexp
    """
    for cell in nb['cells']:
        if cell['cell_type'] != 'markdown':
            continue
        cell['source'] = HTML_COMMENT_RE.sub('', cell['source'])
    return nb


def write_nb(nb, fname):
    with open(fname, 'w', encoding='utf-8') as f:
        nbformat.write(nb, f)


def process_nb(fname, execute=False):
    nb = jupytext.read(fname)
    if execute:
        nb = execute_nb(nb, path_of(fname))
    nb = clear_outputs(nb)
    return clear_md_comments(nb)


def process_dir(path, grade=False, site_dict=None, write_ipynb=True):
    site_dict = {} if site_dict is None else site_dict
    templates = [fn for fn in os.listdir(path) if TEMPLATE_RE.search(fn)]
    if len(templates) == 0:
        raise RuntimeError('No _template.Rmd in directory')
    if len(templates) > 1:
        raise RuntimeError('More than one _template.Rmd in directory')
    template_fname = op.join(path, templates[0])
    template = read_utf8(template_fname)
    if site_dict:
        template = Template(template).render(site=site_dict)
    exercise_fname = TEMPLATE_RE.sub('.Rmd', template_fname)
    write_utf8(exercise_fname, make_exercise(template))
    solution_fname = TEMPLATE_RE.sub('_solution.Rmd', template_fname)
    write_utf8(solution_fname, make_solution(template))
    clear_directory(exercise_fname)
    if write_ipynb:
        write_nb(process_nb(exercise_fname, False),
                 ipynb_fname(exercise_fname))
    if grade:
        grades, messages = gok.grade_nb_fname(solution_fname, path)
        gok.print_grades(grades)
        gok.print_messages(messages)
        if not all(grades.values()):
            raise RuntimeError('One or more grades 0')


def clean_path(path):
    for root, dirs, files in os.walk(path):
        for file in files:
            os.remove(op.join(root, file))
        for d in dirs:
            if d != '.git':
                shutil.rmtree(op.join(root, d))
        break


def write_dir(path, out_path, clean=True, exclude_exts=('.Rmd',)):
    """ Copy exercise files from `path` to directory `out_path`

    `clean`, if True, will clean all files from the eventual output directory
    before copying.

    `exclude_exts` specifies filename extensions that should be excluded from
    output directory.
    """
    if op.isdir(out_path) and clean:
        clean_path(out_path)
    else:
        os.makedirs(out_path)
    for dirpath, dirnames, filenames in os.walk(path):
        sub_dir = op.relpath(dirpath, path)
        dirnames[:] = [d for d in dirnames if good_fname(d)]
        filenames[:] = [f for f in filenames if good_fname(f, exclude_exts)]
        if len(filenames) == 0:
            continue
        this_out_path = op.join(out_path, sub_dir)
        if not op.isdir(this_out_path):
            os.makedirs(this_out_path)
        for f in filenames:
            shutil.copy(op.join(dirpath, f), this_out_path)
