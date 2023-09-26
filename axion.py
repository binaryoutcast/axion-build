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

#%ifdef 0
# Bytecode belongs in ram not on my hard drive.
sys.dont_write_bytecode = True
#%endif

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

#%ifdef 0
def gZoneConfig(aZones, aBasePath):
  # File Content
  zone_base = '''
  zone "{zone}" {lb}
    type {type};
    file "{path}/{zone}.zone";
    allow-query {lb} any; {rb};
  {rb}'''

  # Prep the conf content
  zone_content = ''

  # Iterate over the zones in the configuration json and fill out the conf content
  for _zone in aZones:
    # Master
    _content = zone_base.format(lb = "{", rb = "}",
                                  zone = _zone, type = 'master',
                                  path = aBasePath)
    zone_content += _content

  return zone_content
#%endif

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
#%ifdef 0
      'gZoneConfig': gZoneConfig,
#%endif
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
#%ifdef 0
    'BINOC_NGX_SERVERS': [],
    'BINOC_DNS_BASIC_ZONES': [],
    'BINOC_DNS_ADV_ZONES': [],
    'BINOC_DNS_ZONES': [],
#%endif
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

#%ifdef 0
  if 'BINOC_TARGETS' in exec_locals['CONFIG']:
    # Create targets for BinOC Basic amd Advanced DNS Zones
    for zone in exec_locals['BINOC_DNS_ZONES']:
      zone_defs = dict(exec_locals['DEFINES'], **{
        'BIND_ZONE_DOMAIN': zone,
        'BIND_ZONE_SERIAL': datetime.today().strftime('%Y%m%d%H'),
      })

      if os.path.exists(os.path.abspath(TOPSRCDIR + aDirectory + '/' + zone + '.zone.in')):
        final_target_files += [gTargetFile(zone + '.zone.in', cmd='pp', 
                                           defs=zone_defs, source_dir=aDirectory,
                                           final_target=aDirectory)]
      else:
        final_target_files += [gTargetFile('basic.zone.in', zone + '.zone', cmd='pp', 
                                           defs=zone_defs, source_dir=aDirectory,
                                           final_target=aDirectory)]

    # Create targets for BinOC Nginx Standard Servers
    for server in exec_locals['BINOC_NGX_SERVERS']:
      if server['NGX_SUB_DOMAIN'] == 'www':
        server['NGX_MAIN_SERVER'] = True
      final_target_files += [gTargetFile(
        'standard.server.in',
        '{0}.{1}.server'.format(server['NGX_SUB_DOMAIN'], server['NGX_MAIN_DOMAIN']),
        cmd='pp', defs=server, source_dir=aDirectory, final_target=aDirectory
        )]
#%endif

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
