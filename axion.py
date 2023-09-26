#!/bin/env python2.7

# ===| Setup |=================================================================

from __future__ import print_function
from six import string_types
from collections import OrderedDict
from itertools import chain
from datetime import datetime

import sys
import os
import shutil
import errno
import random
import argparse


from preprocessor import Preprocessor

# -----------------------------------------------------------------------------

# Script Vars
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__)) + os.sep
TOPSRCDIR = SCRIPT_DIR
DIST_DIR = TOPSRCDIR + 'dist/'
FINAL_TARGET = DIST_DIR + 'bin/'
FINAL_TARGET_FILES = []

print('{0}: Starting up...'.format(__file__))

# =============================================================================

# ===| Functions |=============================================================

def gOutput(aMsg):
  print(aMsg)

# -----------------------------------------------------------------------------

def gError(aMsg):
  gOutput(aMsg)
  exit(1)

# -----------------------------------------------------------------------------

def gReadFile(aFile):
  try:
    with open(os.path.abspath(aFile), 'rb') as f:
      rv = f.read()
  except:
    return None

  return rv

# -----------------------------------------------------------------------------


# -----------------------------------------------------------------------------

def gTargetFile(src, target = None, cmd = 'cp', defs = None, source_dir = TOPSRCDIR, final_target = FINAL_TARGET, marker='#'):
  global FINAL_TARGET

  output_prefix = '  '

  # Deal with final_target
  if final_target != FINAL_TARGET:
    final_target = FINAL_TARGET + final_target + os.sep

  if not target:
    target = final_target + os.path.basename(src)
    if src.endswith('.in'):
      target = target[:-3]
  else:
    target = final_target + target

  # Deal with source_dir
  if source_dir != TOPSRCDIR:
    source_dir = TOPSRCDIR + source_dir + os.sep

  if os.path.dirname(src) + os.sep + os.path.basename(src) != src:
    src = source_dir + src

  # Normalize to absolute paths
  src = os.path.abspath(src)
  target = os.path.abspath(target)

  # This structure defines a "rule" in the makefile/mozbuild sense but
  # not over-engineered and cryptic as hell.
  struct = {'outfile': target, 'src': src, 'cmd': cmd}

  if defs or struct['cmd'] == 'pp':
    struct['cmd'] = 'pp'
    struct['ppDefines'] = defs
    output_prefix = '* '
    if target.endswith('.css'):
      struct['ppMarker'] = '%'
    elif target.endswith('.py'):
      struct['ppMarker'] = '#%'
    else:
      struct['ppMarker'] = marker

  gOutput('{0}{1}'.format(output_prefix, target))

  return struct

# -----------------------------------------------------------------------------

def gProcessDirectory(aDirectory = '', aDefines = {}, aConfig = {}):
  global TOPSRCDIR

  # Vars
  final_target_files = []
  build_file = os.path.abspath(TOPSRCDIR + aDirectory + '/axion.build')
  gOutput('Processing {0}'.format(build_file))
  build_exec = gReadFile(build_file)
  config = {}
  defines = {}

  if not build_exec:
    gError('Could not read {0}'.format(build_file))

  # We only want UPPERCASE keys
  for _key, _value in aConfig.iteritems():
    if _key.isupper():
      config[_key] = _value

  for _key, _value in aDefines.iteritems():
    if _key.isupper():
      defines[_key] = _value

  # Set the environment
  exec_globals = {
  '__builtins__': {
      'True': True,
      'False': False,
      'None': None,
      'OrderedDict': OrderedDict,
      'dict': dict,
      'gOutput': gOutput,
      'gError': gError,
      'gTargetFile': gTargetFile,
    }
  }

  exec_locals = {
    'SRC_DIR': aDirectory + os.sep,
    'DIRS': [],
    'CONFIG': config,
    'DEFINES': defines,
    'SRC_FILES': [],
    'SRC_PP_FILES': [],
    'MANUAL_TARGET_FILES': [],
  }

  # Exec the build script so we can harvest the locals
  exec(build_exec, exec_globals, exec_locals)

  # Add manually specified structs to final_target_files
  for struct in exec_locals['MANUAL_TARGET_FILES']:
    final_target_files += [struct]

  # Create targets for Preprocessed Files
  for file in exec_locals['SRC_PP_FILES']:
    final_target_files += [gTargetFile(file, cmd='pp', defs=exec_locals['DEFINES'],
                                       source_dir=aDirectory, final_target=aDirectory)]

  # Create targets for copy operations
  for file in exec_locals['SRC_FILES']:
    final_target_files += [gTargetFile(file, source_dir=aDirectory, final_target=aDirectory)] 


  # We don't do PROPER traversial but we can go to any directory we want from the
  # topsrcdir build file.
  if build_file == TOPSRCDIR + 'axion.build':
    if exec_locals['DIRS']:
      gOutput('- Found the following DIRS: {0}'.format(', '.join(exec_locals['DIRS'])))

    for dir in exec_locals['DIRS']:
      final_target_files += gProcessDirectory(dir, dict(exec_locals['DEFINES']), dict(exec_locals['CONFIG']))

  return final_target_files

# -----------------------------------------------------------------------------

def gProcessTargets(aTargets):
  global TOPSRCDIR
  global FINAL_TARGET

  bin_files = []

  for target in aTargets:
    # Make sure directories exist before we try opening files for read/write
    if not os.path.exists(os.path.dirname(target['outfile'])):
      try:
        os.makedirs(os.path.dirname(target['outfile']))
      except OSError as e:
        # Guard against race condition
        if e.errno != errno.EEXIST:
          raise

    # Print what are going to do
    gOutput('[{0}] {1} -> {2}'.format(target['cmd'],
            target['src'].replace(TOPSRCDIR, "." + os.sep),
            target['outfile']))

    # And do it by preprocessing or copying
    if target['cmd'] == 'pp':
      defines = {}

      # If any defines are None then the are "undef'd"
      for _key, _value in target['ppDefines'].iteritems():
        if _value is None:
          continue
        defines[_key] = _value

      # Create the preprocessor
      pp = Preprocessor(defines=defines, marker=target['ppMarker'])
      
      # We always do substs
      pp.do_filter("substitution")

      # Preprocess.
      with open(target['outfile'], "w") as output:
        with open(target['src'], "r") as input:
          pp.processFile(input=input, output=output)
    elif target['cmd'] == 'cp':
      # We be just a-copyin so do it.
      shutil.copy(target['src'], target['outfile'])
    else:
      gError('Cannot process {0} because the required command could be executed.'.format(target['outfile']))

    # Make sure the 
    if not os.path.exists(target['outfile']):
      gError('An expected output file ({0}) does not actually exist.'.format(target['outfile']))

    bin_files += [ target['outfile'] ]

  return bin_files

# =============================================================================

# ===| Main |==================================================================

# Attempt to remove the dist dir
if os.path.exists(DIST_DIR):
  try:
    shutil.rmtree(DIST_DIR)
  except:
    try:
      shutil.rmtree(DIST_DIR)
    except:
      gError('Could not remove the dist dir. Please try again.')

kNewLine = '\n'
kDot = "."
kDash = '-'
kSpace = " "
kFullLine = '==============================================================================='

gOutput(kFullLine + kNewLine + kSpace + kSpace +
        'Target acquisition (-=info, *=preprocess, blank=copy)' + 
        kNewLine + kFullLine)

# Process TOPSRCDIR
FINAL_TARGET_FILES += gProcessDirectory()

gOutput('')

# -----------------------------------------------------------------------------

output_lines = [
  "Watch and learn, everybody. Watch and learn.",
  "Alright, check THIS out.",
  "Alright, stand back, everybody.",
  "It's my big chance!",
  "Here it comes, pal!",
  "Locked and loaded!",
]

gOutput(kFullLine + kNewLine + kSpace + kSpace +
        random.choice(output_lines) + kNewLine + kFullLine)

# Process all targets 
gProcessTargets(FINAL_TARGET_FILES)

# =============================================================================
