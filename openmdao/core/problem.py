""" OpenMDAO Problem class defintion."""

from openmdao.core.component import Component
from openmdao.core.driver import Driver
from openmdao.core.group import _get_implicit_connections
from openmdao.core.checks.connections import check_connections

from collections import namedtuple

class ConnectError(Exception):
    pass

def make_var_metadata(path, metadata):
    return VarMetadata(path, metadata['val'], type(metadata['val']), metadata.get('shape'))

def check_types_match(src, target):
    if src.type != target.type:
        msg = "Type '{src.path} of source '{src.type}' must be the same as type '{target.path}' of target '{target.type}'"
        msg = msg.format(src=src, target=target)

        raise ConnectError(msg)

def check_connections(connections, params, unknowns):
    # Get metadata for all sources
    sources = map(make_var_metadata, connections.values(), map(unknowns.get, connections.values()))
    
    #Get metadata for all targets
    targets = map(make_var_metadata, connections.keys(), map(params.get, connections.keys()))
    
    for source, target in zip(sources, targets):
        check_types_match(source, target)
        check_shapes_match(source, target)

def check_shapes_match(source, target):
    #Use the type of the shape of source and target to determine which the #correct function to use for shape checking
    source_shape_type = type(source.shape)
    target_shape_type = type(target.shape)
    
    check_shape_function = __shape_checks.get((source_shape_type, target_shape_type), lambda x, y: None)
    
    check_shape_function(source, target)

def __check_shapes_match(src, target):
    if src.shape != target.shape:
        msg  = "Shape '{src.shape}' of the source '{src.path}' must match the shape '{target.shape}' of the target '{target.path}'"
        msg = msg.format(src=src, target=target)

        raise ConnectError(msg)

def __check_val_and_shape_match(src, target):
    if src.val.shape != target.shape:
        msg = "Shape of the initial value '{src.val.shape}' of source '{src.path}' must match the shape '{target.shape}' of the target '{target.path}'"
        msg = msg.format(src=src, target=target)

        raise ConnectError(msg)

VarMetadata = namedtuple('VarMetadata', 'path val type shape')
        
__shape_checks = {
    (tuple, tuple) : __check_shapes_match,
    (type(None), tuple)  : __check_val_and_shape_match
}

class Problem(Component):
    """ The Problem is always the top object for running an OpenMDAO
    model."""

    def __init__(self, root=None, driver=None, impl=None):
        super(Problem, self).__init__()
        self.root = root
        self.impl = impl
        if driver is None:
            self.driver = Driver()
        else:
            self.driver = driver

    def __getitem__(self, name):
        """Retrieve unflattened value of named variable from the root system

        Parameters
        ----------
        name : str   OR   tuple : (name, vector)
             the name of the variable to retrieve from the unknowns vector OR
             a tuple of the name of the variable and the vector to get it's
             value from.

        Returns
        -------
        the unflattened value of the given variable
        """
        return self.root[name]

    def setup(self):
        # Give every system an absolute pathname
        self.root._setup_paths(self.pathname)

        # Give every system a dictionary of parameters and of unknowns
        # that are visible to that system, keyed on absolute pathnames.
        # Metadata for each variable will contain the name of the
        # variable relative to that system as well as size and shape if
        # known.

        # Returns the parameters and unknowns dictionaries for the root.
        params_dict, unknowns_dict = self.root._setup_variables()

        # Get all explicit connections (stated with absolute pathnames)
        connections = self.root._get_explicit_connections()

        # go through relative names of all top level params/unknowns
        # if relative name in unknowns matches relative name in params
        # that indicates an implicit connection. All connections are returned
        # in absolute form.
        implicit_conns = _get_implicit_connections(params_dict, unknowns_dict)

        # check for conflicting explicit/implicit connections
        for tgt, src in connections.items():
            if tgt in implicit_conns:
                msg = '%s is explicitly connected to %s but implicitly connected to %s' % \
                      (tgt, connections[tgt], implicit_conns[tgt])
                raise RuntimeError(msg)

        # combine implicit and explicit connections
        connections.update(implicit_conns)

        check_connections(connections, params_dict, unknowns_dict)

        # check for parameters that are not connected to a source/unknown
        hanging_params = []
        for p in params_dict:
            if p not in connections.keys():
                hanging_params.append(p)

        if hanging_params:
            msg = 'Parameters %s have no associated unknowns.' % hanging_params
            raise RuntimeError(msg)

        # Given connection information, create mapping from system pathname
        # to the parameters that system must transfer data to
        param_owners = assign_parameters(connections)

        # create VarManagers and VecWrappers for all groups in the system tree.
        self.root._setup_vectors(param_owners, connections, impl=self.impl)

    def run(self):
        """ Runs the Driver in self.driver. """
        self.driver.run(self.root)

    def calc_gradient(self, params, unknowns, mode='auto',
                      return_format='array'):
        """ Returns the gradient for the system that is slotted in
        self.root. This function is used by the optimizer, but also can be
        used for testing derivatives on your model.

        Parameters
        ----------
        params : list of strings (optional)
            List of parameter name strings with respect to which derivatives
            are desired. All params must have a paramcomp.

        unknowns : list of strings (optional)
            List of output or state name strings for derivatives to be
            calculated. All must be valid unknowns in OpenMDAO.

        mode : string (optional)
            Deriviative direction, can be 'fwd', 'rev', or 'auto'.
            Default is 'auto', which uses mode specified on the linear solver
            in root.

        return_format : string (optional)
            Format for the derivatives, can be 'array' or 'dict'.

        Returns
        -------
        ndarray or dict
            Jacobian of unknowns with respect to params
        """

        if mode not in ['auto', 'fwd', 'rev']:
            msg = "mode must be 'auto', 'fwd', or 'rev'"
            raise ValueError(msg)

        if return_format not in ['array', 'dict']:
            msg = "return_format must be 'array' or 'dict'"
            raise ValueError(msg)

        # Here, we will assemble right hand sides and call solve_linear on the
        # system in root for each of them.

        pass

def assign_parameters(connections):
    """Map absolute system names to the absolute names of the
    parameters they control.
    """
    param_owners = {}

    for par, unk in connections.items():
        common_parts = []
        for ppart, upart in zip(par.split(':'), unk.split(':')):
            if ppart == upart:
                common_parts.append(ppart)
            else:
                break

        owner = ':'.join(common_parts)
        param_owners.setdefault(owner, []).append(par)

    return param_owners
