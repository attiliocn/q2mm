#!/usr/bin/python
'''
Selects parameters from force fields.

ASSUMES THERE IS NO OVERLAP BETWEEN THE PARAMETERS SELECTED BY THE PARAMETER
FILE AND BY PTYPES!
'''
from __future__ import print_function
import argparse
import logging
import logging.config
import numpy as np
import sys

import constants as co
import datatypes
import filetypes

logger = logging.getLogger(__name__)

ALL_PARM_TYPES = ('ae', 'af', 'be', 'bf', 'df', 'imp1', 'imp2',
                  'sb', 'q', 'vdwe', 'vdwr')

def return_params_parser(add_help=True):
    '''
    Returns an argparse.ArgumentParser object for the selection of
    parameters.
    '''
    if add_help:
        description=(__doc__ + 
                     '''
PTYPES:
ae   - equilibrium angles
af   - angle force constants
be   - equilibrium bond lengths
bf   - bond force constants
df   - dihedral force constants
imp1 - improper torsions (1st MM3* column)
imp2 - improper torsions (2nd MM3* column)
sb   - stretch-bend force constants
q    - bond dipoles
vdwe - van der Waals epsilon
vdwr - van der Waals radius''')
        parser = argparse.ArgumentParser(
            formatter_class=argparse.RawTextHelpFormatter,
            description=description)
    else:
        parser = argparse.ArgumentParser(add_help=False)
    par_group = parser.add_argument_group('parameters')
    par_group.add_argument(
        '--all', '-a', action='store_true',
        help='Select all available parameters from the force field.')
    par_group.add_argument(
        '--average', '-av', type=str, metavar='mm3.fld',
        help=('Use MacroModel files to generate a new force field where\n'
              'each equilibrium value in the optimized section is replaced\n'
              'by the average value from the MacroModel file.'))
    par_group.add_argument(
        '--check', action='store_true',
        help=('Check to see if the selected parameters are used in a\n'
              'MacroModel file. Currently only supports bonds and angles.\n'
              'Stretch-Bends appear to overwrite force field rows in the\n'
              'MacroModel file, resulting in false positives.'))
    par_group.add_argument(
        '--ffpath', '-f', metavar='mm3.fld', default='mm3.fld',
        help='Path to force field.')
    par_group.add_argument(
        '--mmo', '-m', type=str, nargs='+',
        help='Read these MacroModel files.')
    par_group.add_argument(
        '--printparams', '-pp', action='store_true',
        help='Print information about the selected parameters.')
    par_group.add_argument(
        '--pfile', '-pf', type=str, metavar='filename',
        help='Use a file to select parameters. Allows advanced options.')
    par_group.add_argument(
        '--ptypes', '-pt', nargs='+', default=[],
        help='Select these parameter types.')
    return parser

def trim_params_by_type(params, ptypes):
    '''
    Select all parameters with a matching ptype.
    '''
    chosen_params = [x for x in params if x.ptype in ptypes]
    logger.log(15, '  -- Trimmed number of parameters down to {}.'.format(
            len(chosen_params)))
    return chosen_params

def trim_params_by_file(params, filename):
    '''
    Read a parameter file to select parameters.

    Format of parameter file:
    ff_row ff_col [neg]

    ff_row - Integer for line number in mm3.fld.
    ff_col - Integer (1, 2, or 3) for column in mm3.fld. Columns can be
             described as follows:

               A typical MM3* torsion has 3 force constants.
                 V1 = 1
                 V2 = 2
                 V3 = 3

               Similarly, bonds typically use all 3 columns.
                 Equilibrium value = 1
                 Force constant    = 2
                 Bond dipole       = 3

               As my last example, angles (there is no column 3).
                 Equilibrium angle = 1
                 Force constants   = 2

    neg    - Just write the string neg to indicate that it's okay for this
             parameter to have negative values.

    Example parameter file:
      1858 1         # Equilibrium length of bond on line 1858
      1858 2         # Force constant of bond on line 1858
      1859 1         # ...
      1859 2         # ...
      1859 3         # Bond dipole of bond on line 1859
      1872 1         # Equilibrium angle of force constant on line 1872
      1872 2         # Force constant of angle on line 1872
      1891 1 neg     # V1 of torsion on line 1891
      1891 2 neg     # V2 of torsion on line 1891
      1891 3 neg     # V3 of torsion on line 1891
    '''
    # This will hold the parameters you chose.
    chosen_params = []
    # All parameters read from the file.
    temp_params = []
    with open(filename, 'r') as f:
        for line in f:
            line = line.partition('#')[0]
            cols = line.split()
            if cols:
                mm3_row, mm3_col = int(cols[0]), int(cols[1])
                # Check if you allow negative values.
                allow_negative = None
                for arg in cols[2:]:
                    if 'neg' in arg:
                        allow_negative = True
                # Add information to the temporary list.
                temp_params.append((mm3_row, mm3_col, allow_negative))
    # Keep only the parameters that are specified in the file.
    for param in params:
        for temp_param in temp_params:
            if param.mm3_row == temp_param[0] and \
                    param.mm3_col == temp_param[1]:
                # Update the allow negative information.
                param._allow_negative = temp_param[2]
                chosen_params.append(param)
    logger.log(15, '  -- Trimmed number of parameters down to {}.'.format(
            len(chosen_params)))
    return chosen_params

def gather_values(mmos):
    '''
    Gather bonds and angles from MacroModel .mmo files. Could expand to load
    torsions.

    Ex.:
      bond_dic = {1857: [2.2233, 2.2156, 2.5123],
                  1858: [1.3601, 1.3535, 1.3532]
                 }
    '''

    bond_dic = {}
    angle_dic = {}
    for mmo in mmos:
        for structure in mmo.structures:
            for bond in structure.bonds:
                if bond.ff_row in bond_dic:
                    bond_dic[bond.ff_row].append(bond.value)
                else:
                    bond_dic[bond.ff_row] = [bond.value]
            for angle in structure.angles:
                if angle.ff_row in angle_dic:
                    angle_dic[angle.ff_row].append(angle.value)
                else:
                    angle_dic[angle.ff_row] = [angle.value]
    return bond_dic, angle_dic

def main(args):
    '''
    Imports a force field object, which contains a list of all the available
    parameters. Returns a list of only the user selected parameters.
    '''
    if isinstance(args, basestring):
        args = args.split()
    parser = return_params_parser()
    opts = parser.parse_args(args)
    if opts.average or opts.check:
        assert opts.mmo, 'Must provide MacroModel .mmo files!'
    # The function import_ff should be more like something that just
    # interprets filetypes.
    # ff = datatypes.import_ff(opts.ffpath)
    ff = datatypes.MM3(opts.ffpath)
    ff.import_ff()
    # Set the selected parameter types.
    if opts.all:
        opts.ptypes.extend(ALL_PARM_TYPES)
    logger.log(20, 'Selected parameter types: {}'.format(' '.join(opts.ptypes)))
    params = []
    # These two functions populate the selected parameter list. Each takes
    # ff.params and returns a subset of it.
    # WATCH OUT FOR DUPLICATES!
    if opts.ptypes:
        params.extend(trim_params_by_type(ff.params, opts.ptypes))
    if opts.pfile:
        params.extend(trim_params_by_file(ff.params, opts.pfile))
    logger.log(20, '  -- Total number of chosen parameters: {}'.format(
            len(params)))
    # Load MacroModel .mmo files if desired.
    if opts.mmo or opts.average or opts.check:
        mmos = []
        for filename in opts.mmo:
            mmos.append(filetypes.MacroModel(filename))
        bond_dic, angle_dic = gather_values(mmos)
        # Check if the parameter's FF row shows up in the data gathered
        # from the MacroModel .mmo file. Currently only takes into
        # account bonds and angles.
        if opts.check:
            all_rows = bond_dic.keys() + angle_dic.keys()
            for param in params:
                if not param.mm3_row in all_rows:
                    print("{} doesn't appear to be in use.".format(param))
        # Change parameter values to be their averages.
        if opts.average:
            # bond_avg = {1857: 2.3171,
            #             1858: 1.3556
            #            }
            bond_avg = {}
            for ff_row, values in bond_dic.iteritems():
                bond_avg[ff_row] = np.mean(values)
            angle_avg = {}
            for ff_row, values in angle_dic.iteritems():
                angle_avg[ff_row] = np.mean(values)
            # Update parameter values.
            for param in params:
                if param.ptype in ['be', 'ae'] and param.mm3_row in bond_avg:
                    param.value = bond_avg[param.mm3_row]
                if param.ptype in ['be', 'ae'] and param.mm3_row in angle_avg:
                    param.value = angle_avg[param.mm3_row]
            # Export the updated parameters.
            datatypes.export_ff(opts.average, params)
    # Print the parameters.
    if opts.printparams:
        for param in params:
            print('{} {}'.format(param.mm3_row, param.mm3_col))
    ff.params = params
    return ff
                    
if __name__ == '__main__':
    logging.config.dictConfig(co.LOG_SETTINGS)
    main(sys.argv[1:])
