""" OpenMDAO Problem class defintion."""
from __future__ import print_function

from itertools import chain
from collections import OrderedDict
import json
from six import string_types

import networkx as nx

from openmdao.core.group import get_absvarpathnames

class Relevance(object):
    def __init__(self, params_dict, unknowns_dict, connections,
                 inputs, outputs, mode):

        self.params_dict = params_dict
        self.unknowns_dict = unknowns_dict
        self.mode = mode

        param_groups = {}
        output_groups = {}
        g_id = 0

        # turn all inputs and outputs, even singletons, into tuples
        self.inputs = []
        for inp in inputs:
            if isinstance(inp, string_types):
                inp = (inp,)
            if len(inp) == 1:
                param_groups.setdefault(None, []).append(inp[0])
            else:
                param_groups[g_id] = tuple(inp)
                g_id += 1

            self.inputs.append(tuple(inp))

        self.outputs = []
        for out in outputs:
            if isinstance(out, string_types):
                out = (out,)
            if len(out) == 1:
                output_groups.setdefault(None, []).append(out)
            else:
                output_groups[g_id] = tuple(out)
                g_id += 1

            self.outputs.append(out)

        self._vgraph = self._setup_graph(connections)
        self.relevant = self._get_relevant_vars(self._vgraph)

        if mode == 'fwd':
            self.groups = param_groups
        else:
            self.groups = output_groups

    def __getitem__(self, name):
        # if name is None, everything is relevant
        if name is None:
            return set(self._vgraph.nodes())
        return self.relevant.get(name, [])

    def is_relevant(self, var_of_interest, varname):
        if var_of_interest is None:
            return True
        return varname in self.relevant[var_of_interest]

    def vars_of_interest(self, mode=None):
        if mode is None:
            mode = self.mode
        if mode == 'fwd':
            return self.inputs
        elif mode == 'rev':
            return self.outputs
        else:
            return self.inputs+self.outputs

    def _setup_graph(self, connections):
        """
        Set up a dependency graph for all variables in the Problem.

        Returns
        -------
        nx.DiGraph
            A graph containing all variables and their connections

        """
        params_dict = self.params_dict
        unknowns_dict = self.unknowns_dict

        vgraph = nx.DiGraph()  # var graph

        compins = {}  # maps input vars to components
        compouts = {} # maps output vars to components

        promote_map = {}

        for param, meta in params_dict.items():
            tcomp = param.rsplit('.',1)[0]
            compins.setdefault(tcomp, []).append(param)
            if param in connections and meta['promoted_name'] != param:
                promote_map[param] = meta['promoted_name']

        for unknown, meta in unknowns_dict.items():
            scomp = unknown.rsplit('.',1)[0]
            compouts.setdefault(scomp, []).append(unknown)
            if meta['promoted_name'] != unknown:
                promote_map[unknown] = meta['promoted_name']

        for target, source in connections.items():
            vgraph.add_edge(source, target)

        # connect inputs to outputs on same component in order to fully
        # connect the variable graph.
        for comp, inputs in compins.items():
            for inp in inputs:
                for out in compouts.get(comp, ()):
                    vgraph.add_edge(inp, out)

        # now collapse any var nodes with implicit connections
        nx.relabel_nodes(vgraph, promote_map, copy=False)

        # remove any self edges created by the relabeling
        for u,v in vgraph.edges():
            if u == v:
                vgraph.remove_edge(u, v)

        return vgraph

    def _get_relevant_vars(self, g):
        """
        Args
        ----
        g : nx.DiGraph
            A graph of variable dependencies.

        Returns
        -------
        dict
            Dictionary that maps a variable name to all other variables in the graph that
            are relevant to it.
        """
        succs = {}
        for nodes in self.inputs:
            for node in nodes:
                succs[node] = set([v for u,v in nx.dfs_edges(g, node)])
                succs[node].add(node)

        relevant = {}
        grev = g.reverse()
        for nodes in self.outputs:
            for node in nodes:
                relevant[node] = set()
                preds = set([v for u,v in nx.dfs_edges(grev, node)])
                preds.add(node)
                for inps in self.inputs:
                    for inp in inps:
                        common = preds.intersection(succs[inp])
                        relevant[node].update(common)
                        relevant.setdefault(inp, set()).update(common)

        return relevant

    def json_dependencies(self):
        """
        Returns
        -------
        A json string with a dependency matrix and a list of variable
        name labels.
        """
        idxs = OrderedDict()
        matrix = []
        size = len(self._vgraph.nodes())

        for i, node in enumerate(self._vgraph.nodes_iter()):
            idxs[node] = i
            matrix.append([0]*size)

        for u, v in self._vgraph.edges_iter():
            matrix[idxs[u]][idxs[v]] = 1

        dct = {
            'dependencies': {
                'matrix' : matrix,
                'labels' : self._vgraph.nodes()
            }
        }

        return json.dumps(dct)